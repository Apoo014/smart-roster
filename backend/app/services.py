"""Service layer: loads data into the pure engine, persists results, builds dashboard/report payloads."""
import csv
import io
from collections import defaultdict
from datetime import date, datetime, timedelta
from typing import List, Optional

from sqlalchemy.orm import Session

from . import engine as E
from .models import (Assignment, Brand, Conflict, Employee, Holiday, Leave, Pod, Process, Roster,
                     RosterEntry, WeeklyOff, WorkingRule)

SEV_ORDER = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3}


# ---------------------------------------------------------------- loading
def build_context(db: Session) -> E.Context:
    ctx = E.Context()
    for e in db.query(Employee).all():
        ctx.employees[e.id] = dict(name=e.name, active=(e.status == "ACTIVE"), pod_id=e.pod_id,
                                   capacity=e.daily_capacity or 2)
    active_brands = set()
    for b in db.query(Brand).all():
        ctx.brand_names[b.id] = b.name
        ctx.brand_pod[b.id] = b.pod_id
        if b.status == "ACTIVE":
            active_brands.add(b.id)
    for p in db.query(Process).all():
        ctx.process_names[p.id] = p.name
    for r in db.query(WorkingRule).all():
        if r.brand_id in active_brands:
            ctx.rules[(r.brand_id, r.process_id)] = dict(calendar=r.calendar_type, min_staff=r.min_staff or 1)
    for a in db.query(Assignment).all():
        if a.brand_id in active_brands:
            ctx.assignments.append((a.employee_id, a.brand_id, a.process_id))
    for w in db.query(WeeklyOff).all():
        ctx.weekly_offs.setdefault(w.employee_id, set()).add(w.weekday)
    for lv in db.query(Leave).filter(Leave.status == "APPROVED").all():
        ctx.leaves.setdefault(lv.employee_id, []).append((lv.start_date, lv.end_date, lv.leave_type))
    ctx.holidays = {h.date for h in db.query(Holiday).all()}
    return ctx


def load_entries(db: Session, roster_id: int) -> List[E.Entry]:
    return [E.Entry(r.employee_id, r.brand_id, r.process_id, r.date, r.status, bool(r.cover), bool(r.manual), r.id)
            for r in db.query(RosterEntry).filter(RosterEntry.roster_id == roster_id).all()]


def get_roster(db: Session, month: int, year: int) -> Optional[Roster]:
    return db.query(Roster).filter(Roster.month == month, Roster.year == year).first()


# ---------------------------------------------------------------- conflicts persistence
def _ckey(type_, d, b, p, e):
    return (type_, d, b, p, e)


def replace_conflicts(db: Session, roster: Roster, new: List[dict], cells=None, emp_dates=None) -> List[Conflict]:
    """Replace conflicts inside the validated scope. Acknowledged flags survive; they never hide a conflict."""
    full = cells is None and emp_dates is None
    old = db.query(Conflict).filter(Conflict.roster_id == roster.id).all()
    ack = {_ckey(c.type, c.date, c.brand_id, c.process_id, c.employee_id) for c in old if c.status == "ACKNOWLEDGED"}
    for c in old:
        remove = full
        if not full:
            if c.type == E.COVERAGE_GAP:
                remove = cells is not None and (c.brand_id, c.process_id, c.date) in cells
            elif c.type in E.ENTRY_CONFLICT_TYPES:
                remove = emp_dates is not None and (c.employee_id, c.date) in emp_dates
        if remove:
            db.delete(c)
    created = []
    for n in new:
        row = Conflict(roster_id=roster.id, date=n["date"], brand_id=n.get("brand_id"), process_id=n.get("process_id"),
                       employee_id=n.get("employee_id"), type=n["type"], severity=n["severity"],
                       description=n["description"], suggestion=n.get("suggestion", ""),
                       backup_ids=n.get("backup_ids", ""),
                       status="ACKNOWLEDGED" if _ckey(n["type"], n["date"], n.get("brand_id"), n.get("process_id"),
                                                      n.get("employee_id")) in ack else "OPEN")
        db.add(row)
        created.append(row)
    db.flush()
    return created


def validate_full(db: Session, roster: Roster) -> List[Conflict]:
    ctx = build_context(db)
    entries = load_entries(db, roster.id)
    dates = E.month_dates(roster.year, roster.month)
    found = E.compute_conflicts(ctx, entries, dates)
    rows = replace_conflicts(db, roster, found)
    db.commit()
    return rows


def _validate_scope(db, roster, ctx, entries, cells, emp_dates):
    dates = E.month_dates(roster.year, roster.month)
    found = E.compute_conflicts(ctx, entries, dates, cells=cells, emp_dates=emp_dates)
    return replace_conflicts(db, roster, found, cells=cells, emp_dates=emp_dates)


# ---------------------------------------------------------------- generation
def generate_roster(db: Session, month: int, year: int, force: bool = False, keep_manual: bool = True) -> Roster:
    roster = get_roster(db, month, year)
    if roster and roster.status == "PUBLISHED" and not force:
        raise ValueError("This roster is published. Re-generating would overwrite it - confirm with force=true.")
    ctx = build_context(db)
    dates = E.month_dates(year, month)
    kept_manual, kept_cover = {}, []
    if roster:
        for en in load_entries(db, roster.id):
            if en.cover:
                kept_cover.append(en)
            elif en.manual and keep_manual:
                kept_manual[(en.employee_id, en.brand_id, en.process_id, en.date)] = en
        db.query(RosterEntry).filter(RosterEntry.roster_id == roster.id).delete()
        db.query(Conflict).filter(Conflict.roster_id == roster.id).delete()
        roster.status = "DRAFT"
    else:
        roster = Roster(month=month, year=year, status="DRAFT")
        db.add(roster)
        db.flush()
    entries = E.generate_entries(ctx, dates)
    for en in entries:
        old = kept_manual.get((en.employee_id, en.brand_id, en.process_id, en.date))
        if old is not None:
            en.status, en.manual = old.status, True
    for cv in kept_cover:
        if E.employee_state(ctx, cv.employee_id, cv.date) not in (E.L, E.C):
            entries.append(cv)
    db.bulk_save_objects([RosterEntry(roster_id=roster.id, employee_id=e.employee_id, brand_id=e.brand_id,
                                      process_id=e.process_id, date=e.date, status=e.status,
                                      manual=e.manual, cover=e.cover) for e in entries])
    roster.generated_at = datetime.utcnow()
    db.flush()
    found = E.compute_conflicts(ctx, entries, dates)
    replace_conflicts(db, roster, found)
    db.commit()
    return roster


# ---------------------------------------------------------------- manual edits
def edit_entry(db: Session, entry_id: int, status: str):
    row = db.get(RosterEntry, entry_id)
    if row is None:
        raise LookupError("Entry not found")
    if status not in E.STATUS_CODES:
        raise ValueError(f"Status must be one of {', '.join(E.STATUS_CODES)}")
    roster = db.get(Roster, row.roster_id)
    row.status, row.manual = status, True
    if roster.status != "DRAFT":
        roster.status = "DRAFT"
    db.flush()
    ctx = build_context(db)
    entries = load_entries(db, roster.id)
    created = _validate_scope(db, roster, ctx, entries, {(row.brand_id, row.process_id, row.date)},
                              {(row.employee_id, row.date)})
    db.commit()
    return created


def add_cover(db: Session, roster_id: int, employee_id: int, brand_id: int, process_id: int, d: date):
    roster = db.get(Roster, roster_id)
    row = (db.query(RosterEntry).filter(RosterEntry.roster_id == roster_id, RosterEntry.employee_id == employee_id,
                                        RosterEntry.brand_id == brand_id, RosterEntry.process_id == process_id,
                                        RosterEntry.date == d).first())
    if row:
        row.status, row.manual = E.W, True
    else:
        row = RosterEntry(roster_id=roster_id, employee_id=employee_id, brand_id=brand_id, process_id=process_id,
                          date=d, status=E.W, manual=True, cover=True)
        db.add(row)
    roster.status = "DRAFT"
    db.flush()
    ctx = build_context(db)
    entries = load_entries(db, roster_id)
    created = _validate_scope(db, roster, ctx, entries, {(brand_id, process_id, d)}, {(employee_id, d)})
    db.commit()
    return created


def delete_cover(db: Session, entry_id: int):
    row = db.get(RosterEntry, entry_id)
    if row is None or not row.cover:
        raise ValueError("Only cover shifts can be removed; edit the status of normal shifts instead.")
    roster = db.get(Roster, row.roster_id)
    cell, emp = {(row.brand_id, row.process_id, row.date)}, {(row.employee_id, row.date)}
    db.delete(row)
    db.flush()
    ctx = build_context(db)
    created = _validate_scope(db, roster, ctx, load_entries(db, roster.id), cell, emp)
    db.commit()
    return created


# ---------------------------------------------------------------- change management
def apply_availability_change(db: Session, employee_id: int, start: date, end: date) -> dict:
    """Leave approved/rejected/removed -> refresh only the affected entries, then validate only those cells."""
    ctx = build_context(db)
    impact = dict(rosters=[], affected_entries=0, new_conflicts=[])
    q = db.query(Roster)
    for roster in q.all():
        first, last = date(roster.year, roster.month, 1), E.month_dates(roster.year, roster.month)[-1]
        if end < first or start > last:
            continue
        entries = load_entries(db, roster.id)
        changed, removed = E.recompute_statuses(ctx, entries, employee_id, max(start, first), min(end, last))
        by_id = {e.id: e for e in changed}
        for row in db.query(RosterEntry).filter(RosterEntry.id.in_(list(by_id) or [-1])).all():
            row.status = by_id[row.id].status
        for r in removed:
            db.query(RosterEntry).filter(RosterEntry.id == r.id).delete()
        removed_ids = {r.id for r in removed}
        entries = [e for e in entries if e.id not in removed_ids]
        db.flush()
        touched = changed + removed
        if not touched:
            continue
        cells = {(e.brand_id, e.process_id, e.date) for e in touched}
        emp_dates = {(e.employee_id, e.date) for e in touched}
        created = _validate_scope(db, roster, ctx, entries, cells, emp_dates)
        if roster.status == "PUBLISHED":
            roster.status = "DRAFT"
        impact["rosters"].append(f"{roster.month:02d}/{roster.year}")
        impact["affected_entries"] += len(touched)
        impact["new_conflicts"] += [conflict_dict(c, ctx) for c in created]
    db.commit()
    return impact


def publish(db: Session, roster: Roster, force: bool = False) -> dict:
    blocking = db.query(Conflict).filter(Conflict.roster_id == roster.id,
                                         Conflict.severity.in_(["CRITICAL", "HIGH"])).count()
    if blocking and not force:
        return dict(published=False, blocking=blocking,
                    message=f"{blocking} critical/high conflicts are still unresolved. "
                            f"Fix them, or publish anyway with an explicit override.")
    roster.status = "PUBLISHED"
    roster.note = f"Published with {blocking} unresolved critical/high conflicts (manager override)." if blocking else ""
    db.commit()
    return dict(published=True, blocking=blocking, message="Roster published.")


# ---------------------------------------------------------------- serializers
def conflict_dict(c: Conflict, ctx: E.Context) -> dict:
    return dict(id=c.id, date=c.date.isoformat() if c.date else None, brand_id=c.brand_id,
                brand=ctx.bn(c.brand_id) if c.brand_id else None,
                process_id=c.process_id, process=ctx.pn(c.process_id) if c.process_id else None,
                employee_id=c.employee_id, employee=ctx.en(c.employee_id) if c.employee_id else None,
                type=c.type, severity=c.severity, description=c.description, suggestion=c.suggestion,
                status=c.status,
                backups=[dict(id=int(i), name=ctx.en(int(i))) for i in (c.backup_ids or "").split(",") if i])


def list_conflicts(db: Session, roster_id: int, ctx: Optional[E.Context] = None) -> List[dict]:
    ctx = ctx or build_context(db)
    rows = db.query(Conflict).filter(Conflict.roster_id == roster_id).all()
    rows.sort(key=lambda c: (SEV_ORDER.get(c.severity, 9), c.date or date.min, c.brand_id or 0))
    return [conflict_dict(c, ctx) for c in rows]


def roster_summary(db: Session, roster: Roster, ctx=None, entries=None) -> dict:
    ctx = ctx or build_context(db)
    entries = entries if entries is not None else load_entries(db, roster.id)
    dates = E.month_dates(roster.year, roster.month)
    stats = E.coverage_stats(ctx, entries, dates)
    counts = defaultdict(int)
    for c in db.query(Conflict).filter(Conflict.roster_id == roster.id).all():
        counts[c.severity] += 1
    return dict(id=roster.id, month=roster.month, year=roster.year, status=roster.status, note=roster.note or "",
                generated_at=roster.generated_at.isoformat() if roster.generated_at else None,
                coverage_percent=stats["percent"], required_slots=stats["required"], covered_slots=stats["covered"],
                conflicts=dict(critical=counts["CRITICAL"], high=counts["HIGH"], medium=counts["MEDIUM"],
                               low=counts["LOW"], total=sum(counts.values())))


def roster_grid(db: Session, roster: Roster) -> dict:
    ctx = build_context(db)
    entries = load_entries(db, roster.id)
    dates = E.month_dates(roster.year, roster.month)
    rows = {}
    assigned = set(ctx.assignments)
    for en in sorted(entries, key=lambda x: (ctx.en(x.employee_id), x.brand_id, x.process_id, x.date)):
        key = (en.employee_id, en.brand_id, en.process_id)
        if key not in rows:
            info = ctx.employees.get(en.employee_id, {})
            rows[key] = dict(employee_id=en.employee_id, employee=ctx.en(en.employee_id), pod_id=info.get("pod_id"),
                             brand_id=en.brand_id, brand=ctx.bn(en.brand_id), process_id=en.process_id,
                             process=ctx.pn(en.process_id), cover=key not in assigned, cells={})
        rows[key]["cells"][en.date.isoformat()] = dict(id=en.id, s=en.status, m=en.manual, c=en.cover)
    bad_cells = sorted({f"{c.brand_id}-{c.process_id}-{c.date.isoformat()}"
                        for c in db.query(Conflict).filter(Conflict.roster_id == roster.id,
                                                           Conflict.type == E.COVERAGE_GAP).all()})
    return dict(roster=roster_summary(db, roster, ctx, entries),
                dates=[d.isoformat() for d in dates], holidays=sorted(d.isoformat() for d in ctx.holidays
                                                                      if d in set(dates)),
                rows=sorted(rows.values(), key=lambda r: (r["brand"], r["process"], r["employee"])),
                gap_cells=bad_cells)


def export_csv(db: Session, roster: Roster) -> str:
    grid = roster_grid(db, roster)
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(["Employee", "Brand", "Process"] + [d[8:] for d in grid["dates"]])
    for r in grid["rows"]:
        w.writerow([r["employee"], r["brand"], r["process"]] + [r["cells"].get(d, {}).get("s", "") for d in grid["dates"]])
    return out.getvalue()


# ---------------------------------------------------------------- dashboard + reports
def dashboard(db: Session, month: int, year: int) -> dict:
    ctx = build_context(db)
    today = date.today()
    active = [e for e, i in ctx.employees.items() if i["active"]]
    working = leave = off = 0
    schedule = []
    by_emp = defaultdict(list)
    for e, b, p in ctx.assignments:
        by_emp[e].append((b, p))
    for e in active:
        st = E.employee_state(ctx, e, today)
        if st in (E.L, E.C):
            leave += 1
        elif st == E.O:
            off += 1
        else:
            working += 1
        brands = sorted({ctx.bn(b) for b, p in by_emp.get(e, []) if E.is_operational(ctx, b, p, today)})
        schedule.append(dict(employee=ctx.en(e), status=st or E.W, brands=", ".join(brands) or "-"))
    schedule.sort(key=lambda s: ({"W": 0}.get(s["status"], 1), s["employee"]))

    pods = db.query(Pod).all()
    pod_dist = [dict(pod=p.name, count=sum(1 for e in active if ctx.employees[e]["pod_id"] == p.id)) for p in pods]

    roster = get_roster(db, month, year)
    kpi = dict(employees=len(active), brands=len({b for b, _ in ctx.rules}), pods=len(pods),
               working_today=working, on_leave=leave, weekly_off=off, coverage=None, conflicts=0)
    payload = dict(kpi=kpi, pod_distribution=pod_dist, brand_coverage=[], availability=[], workload=[],
                   recent_conflicts=[], attention=[], schedule_today=schedule, roster=None,
                   holidays=[dict(date=h.date.isoformat(), name=h.name)
                             for h in db.query(Holiday).filter(Holiday.date >= today).order_by(Holiday.date).limit(5)])
    if not roster:
        return payload
    entries = load_entries(db, roster.id)
    dates = E.month_dates(year, month)
    summ = roster_summary(db, roster, ctx, entries)
    stats = E.coverage_stats(ctx, entries, dates)
    kpi["coverage"] = summ["coverage_percent"]
    kpi["conflicts"] = summ["conflicts"]["critical"] + summ["conflicts"]["high"] + summ["conflicts"]["medium"]
    payload["roster"] = summ
    bc = sorted(({"brand": ctx.bn(b), "percent": v["percent"], "required": v["required"], "covered": v["covered"]}
                 for b, v in stats["per_brand"].items()), key=lambda x: (x["percent"], x["brand"]))
    payload["brand_coverage"] = bc
    payload["attention"] = [x for x in bc if x["percent"] < 100][:6]
    day_state = defaultdict(dict)
    worked = defaultdict(int)
    for en in entries:
        cur = day_state[en.date].get(en.employee_id)
        rank = {"W": 3, "L": 2, "C": 2, "O": 1}
        if en.status in rank and (cur is None or rank[en.status] > rank[cur]):
            day_state[en.date][en.employee_id] = en.status
        if en.status == "W":
            worked[(en.employee_id, en.date)] = 1
    for d in dates:
        vals = list(day_state[d].values())
        payload["availability"].append(dict(date=d.isoformat(), working=vals.count("W"),
                                            leave=vals.count("L") + vals.count("C"), off=vals.count("O")))
    days_worked = defaultdict(int)
    for (e, _d) in worked:
        days_worked[e] += 1
    payload["workload"] = sorted(({"employee": ctx.en(e).split()[0], "days": n} for e, n in days_worked.items()),
                                 key=lambda x: -x["days"])
    payload["recent_conflicts"] = list_conflicts(db, roster.id, ctx)[:8]
    return payload


def reports(db: Session, month: int, year: int) -> dict:
    ctx = build_context(db)
    roster = get_roster(db, month, year)
    out = dict(roster=None, utilization=[], brand_coverage=[], process_staffing=[], weekly_off=[], leave=[])
    for wd in range(7):
        out["weekly_off"].append(dict(day=E.WEEKDAYS[wd], employees=sum(1 for e, s in ctx.weekly_offs.items()
                                                                         if wd in s and ctx.employees[e]["active"])))
    lv = defaultdict(int)
    for l in db.query(Leave).all():
        lv[(l.leave_type, l.status)] += (l.end_date - l.start_date).days + 1
    out["leave"] = [dict(type=k[0], status=k[1], days=v) for k, v in sorted(lv.items())]
    if not roster:
        return out
    entries = load_entries(db, roster.id)
    dates = E.month_dates(year, month)
    out["roster"] = roster_summary(db, roster, ctx, entries)
    stats = E.coverage_stats(ctx, entries, dates)
    out["brand_coverage"] = sorted((dict(brand=ctx.bn(b), **v) for b, v in stats["per_brand"].items()),
                                   key=lambda x: x["brand"])
    out["process_staffing"] = [dict(process=ctx.pn(p), **v) for p, v in sorted(stats["per_process"].items())]
    per = defaultdict(lambda: defaultdict(set))
    for en in entries:
        per[en.employee_id][en.status].add(en.date)
    brands_per = defaultdict(set)
    for e, b, _ in ctx.assignments:
        brands_per[e].add(b)
    for e in sorted(ctx.employees, key=lambda x: ctx.en(x)):
        if not ctx.employees[e]["active"]:
            continue
        s = per.get(e, {})
        w = len(s.get("W", set()))
        out["utilization"].append(dict(employee=ctx.en(e), brands=len(brands_per.get(e, ())), working=w,
                                       weekly_off=len(s.get("O", set())), leave=len(s.get("L", set()) | s.get("C", set())),
                                       utilization=round(100 * w / len(dates)) if dates else 0))
    return out
