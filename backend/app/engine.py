"""
Pure-Python scheduling + validation engine.

No database or web-framework imports live here on purpose: the engine receives a
`Context` (plain data) and returns plain data. That makes it easy to test and to
swap for an OR-Tools model later without touching the API or database layers.
"""
from __future__ import annotations

import calendar
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Dict, Iterable, List, Optional, Set, Tuple

# ---- constants -------------------------------------------------------------
CAL_365 = "365"                       # open every day, incl. Sundays + holidays
CAL_HOLIDAY_OFF = "HOLIDAY_OFF"       # open every day except public holidays
CAL_SUNDAY_HOLIDAY_OFF = "SUNDAY_HOLIDAY_OFF"  # closed Sundays + public holidays
CALENDAR_TYPES = (CAL_365, CAL_HOLIDAY_OFF, CAL_SUNDAY_HOLIDAY_OFF)

# Roster cell codes. W/O/L/H/C come from the blueprint; X = brand closed (non-holiday Sunday).
W, O, L, H, C, X = "W", "O", "L", "H", "C", "X"
STATUS_CODES = (W, O, L, H, C, X)

WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]

CRITICAL, HIGH, MEDIUM, LOW = "CRITICAL", "HIGH", "MEDIUM", "LOW"

COVERAGE_GAP = "COVERAGE_GAP"
LEAVE_VIOLATION = "LEAVE_VIOLATION"
WEEKLY_OFF_VIOLATION = "WEEKLY_OFF_VIOLATION"
OVERLOAD = "OVERLOAD"
INVALID_ASSIGNMENT = "INVALID_ASSIGNMENT"
CONSECUTIVE_WORK = "CONSECUTIVE_WORK"

ENTRY_CONFLICT_TYPES = {LEAVE_VIOLATION, WEEKLY_OFF_VIOLATION, OVERLOAD, INVALID_ASSIGNMENT}
MAX_CONSECUTIVE_DAYS = 6


# ---- data structures -------------------------------------------------------
@dataclass
class Entry:
    employee_id: int
    brand_id: int
    process_id: int
    date: date
    status: str
    cover: bool = False      # True = backup/cover shift added by a manager
    manual: bool = False     # True = edited by a person (the generator will not overwrite it)
    id: Optional[int] = None


@dataclass
class Context:
    employees: Dict[int, dict] = field(default_factory=dict)      # id -> {name, active, pod_id, capacity}
    assignments: List[Tuple[int, int, int]] = field(default_factory=list)  # (employee, brand, process)
    rules: Dict[Tuple[int, int], dict] = field(default_factory=dict)       # (brand, process) -> {calendar, min_staff}
    weekly_offs: Dict[int, Set[int]] = field(default_factory=dict)         # employee -> {weekday 0=Mon}
    leaves: Dict[int, List[tuple]] = field(default_factory=dict)           # employee -> [(start, end, type)] APPROVED only
    holidays: Set[date] = field(default_factory=set)
    brand_pod: Dict[int, Optional[int]] = field(default_factory=dict)
    brand_names: Dict[int, str] = field(default_factory=dict)
    process_names: Dict[int, str] = field(default_factory=dict)

    # -- name helpers
    def bn(self, b): return self.brand_names.get(b, f"Brand#{b}")
    def pn(self, p): return self.process_names.get(p, f"Process#{p}")
    def en(self, e): return self.employees.get(e, {}).get("name", f"Employee#{e}")


# ---- calendar helpers ------------------------------------------------------
def month_dates(year: int, month: int) -> List[date]:
    n = calendar.monthrange(year, month)[1]
    return [date(year, month, d) for d in range(1, n + 1)]


def is_operational(ctx: Context, brand_id: int, process_id: int, d: date) -> bool:
    """Does the CLIENT need service on this date? (brand/process calendar, not employee schedule)"""
    rule = ctx.rules.get((brand_id, process_id))
    if rule is None:
        return False
    cal = rule["calendar"]
    if cal == CAL_365:
        return True
    if d in ctx.holidays:
        return False
    if cal == CAL_SUNDAY_HOLIDAY_OFF and d.weekday() == 6:
        return False
    return True


def employee_state(ctx: Context, emp_id: int, d: date) -> Optional[str]:
    """Personal availability: 'L' leave, 'C' comp-off, 'O' weekly off, or None if available."""
    for start, end, ltype in ctx.leaves.get(emp_id, []):
        if start <= d <= end:
            return C if str(ltype).lower().replace("-", "").replace("_", "").replace(" ", "") == "compoff" else L
    if d.weekday() in ctx.weekly_offs.get(emp_id, set()):
        return O
    return None


def entry_status(ctx: Context, emp_id: int, brand_id: int, process_id: int, d: date) -> str:
    if not is_operational(ctx, brand_id, process_id, d):
        if d in ctx.holidays:
            return H
        return O if d.weekday() in ctx.weekly_offs.get(emp_id, set()) else X
    return employee_state(ctx, emp_id, d) or W


# ---- generation ------------------------------------------------------------
def generate_entries(ctx: Context, dates: Iterable[date]) -> List[Entry]:
    """
    Deterministic rule-based generation (stages 2-6 of the blueprint):
    every active assignee works every day the brand is open and they are available.
    Weekly offs are honoured as mandatory; if that leaves a required slot uncovered
    the engine does NOT silently override the off day - validation flags a gap instead.
    """
    entries: List[Entry] = []
    assignments = sorted(a for a in ctx.assignments if ctx.employees.get(a[0], {}).get("active"))
    for d in dates:
        for e, b, p in assignments:
            if (b, p) not in ctx.rules:
                continue
            entries.append(Entry(e, b, p, d, entry_status(ctx, e, b, p, d)))
    return entries


def recompute_statuses(ctx: Context, entries: List[Entry], emp_id: int, start: date, end: date):
    """
    Incremental refresh after an availability change (e.g. leave approved).
    Returns (changed_entries, removed_entries). Cover shifts that now clash with leave are removed;
    manual edits are kept unless leave/comp-off now applies.
    """
    changed, removed = [], []
    for en in entries:
        if en.employee_id != emp_id or not (start <= en.date <= end):
            continue
        new = entry_status(ctx, emp_id, en.brand_id, en.process_id, en.date)
        state = employee_state(ctx, emp_id, en.date)
        if en.cover:
            if state in (L, C):
                removed.append(en)
            continue
        if en.manual and state not in (L, C) and en.status != L and en.status != C:
            continue
        if new != en.status:
            en.status = new
            changed.append(en)
    return changed, removed


# ---- validation ------------------------------------------------------------
def _valid_working(ctx, entries):
    """(brand, process, date) -> set(employee) of entries that really cover the slot."""
    cov = defaultdict(set)
    for en in entries:
        if en.status == W and employee_state(ctx, en.employee_id, en.date) not in (L, C):
            if ctx.employees.get(en.employee_id, {}).get("active", False):
                cov[(en.brand_id, en.process_id, en.date)].add(en.employee_id)
    return cov


def _day_brands(entries):
    out = defaultdict(set)
    for en in entries:
        if en.status == W:
            out[(en.employee_id, en.date)].add(en.brand_id)
    return out


def suggest_backups(ctx, day_brands, brand_id, process_id, d, already: Set[int], limit=3):
    ranked = []
    assigned_here = {e for e, b, _ in ctx.assignments if b == brand_id}
    for e, info in ctx.employees.items():
        if not info.get("active") or e in already:
            continue
        if employee_state(ctx, e, d) is not None:
            continue
        brands = day_brands.get((e, d), set())
        if brand_id not in brands and len(brands) >= info.get("capacity", 2):
            continue
        if e in assigned_here:
            rank, why = 0, "already on this brand"
        elif ctx.brand_pod.get(brand_id) is not None and info.get("pod_id") == ctx.brand_pod.get(brand_id):
            rank, why = 1, "same pod"
        else:
            rank, why = 2, "free that day"
        ranked.append((rank, info["name"], e, why))
    ranked.sort()
    return [(e, name, why) for _, name, e, why in ranked[:limit]]


def compute_conflicts(ctx: Context, entries: List[Entry], dates: List[date],
                      cells: Optional[Set[tuple]] = None,
                      emp_dates: Optional[Set[tuple]] = None) -> List[dict]:
    """
    Hard-constraint validation. With cells/emp_dates=None the whole roster is checked;
    otherwise only the given (brand, process, date) cells and (employee, date) pairs
    are re-checked (incremental validation).
    """
    out: List[dict] = []
    cov = _valid_working(ctx, entries)
    day_brands = _day_brands(entries)
    full = cells is None and emp_dates is None

    # 1) coverage per required brand-process-date
    for d in dates:
        for (b, p), rule in sorted(ctx.rules.items()):
            if cells is not None and (b, p, d) not in cells:
                continue
            if not is_operational(ctx, b, p, d):
                continue
            need = rule["min_staff"]
            have = cov.get((b, p, d), set())
            if len(have) >= need:
                continue
            reasons = []
            for e, eb, ep in ctx.assignments:
                if eb == b and ep == p and ctx.employees.get(e, {}).get("active"):
                    st = employee_state(ctx, e, d)
                    label = {L: "on leave", C: "on comp-off", O: "on weekly off"}.get(st, "not scheduled")
                    if e not in have:
                        reasons.append(f"{ctx.en(e)} ({label})")
            if not any(a[1] == b and a[2] == p for a in ctx.assignments):
                reasons.append("nobody is assigned to this process")
            backups = suggest_backups(ctx, day_brands, b, p, d, have)
            sug = "Assign a qualified backup employee"
            if backups:
                sug += ": " + ", ".join(f"{n} ({w})" for _, n, w in backups)
            sug += ", or revisit the weekly off / leave of the assigned employee."
            out.append(dict(
                date=d, brand_id=b, process_id=p, employee_id=None, type=COVERAGE_GAP, severity=CRITICAL,
                description=(f"{ctx.bn(b)} / {ctx.pn(p)} on {d.isoformat()} ({WEEKDAYS[d.weekday()]}): "
                             f"required {need}, available {len(have)}, short by {need - len(have)}. "
                             f"Reason: {'; '.join(reasons) or 'no eligible employee'}."),
                suggestion=sug, backup_ids=",".join(str(e) for e, _, _ in backups)))

    # 2) per-entry hard constraints
    assigned = set(ctx.assignments)
    for en in entries:
        if en.status != W:
            continue
        if emp_dates is not None and (en.employee_id, en.date) not in emp_dates:
            continue
        info = ctx.employees.get(en.employee_id)
        who = ctx.en(en.employee_id)
        base = dict(date=en.date, brand_id=en.brand_id, process_id=en.process_id, employee_id=en.employee_id,
                    backup_ids="")
        st = employee_state(ctx, en.employee_id, en.date)
        if st in (L, C):
            out.append({**base, "type": LEAVE_VIOLATION, "severity": HIGH,
                        "description": f"{who} is scheduled on {en.date.isoformat()} but is on approved "
                                       f"{'comp-off' if st == C else 'leave'}.",
                        "suggestion": "Remove this shift and assign a backup."})
        elif st == O:
            out.append({**base, "type": WEEKLY_OFF_VIOLATION, "severity": HIGH,
                        "description": f"{who} is scheduled on {en.date.isoformat()} which is their weekly off.",
                        "suggestion": "Grant the weekly off and cover the shift, or move the weekly off."})
        if not info or not info.get("active"):
            out.append({**base, "type": INVALID_ASSIGNMENT, "severity": HIGH,
                        "description": f"{who} is inactive but scheduled on {en.date.isoformat()}.",
                        "suggestion": "Remove the shift."})
        elif (en.employee_id, en.brand_id, en.process_id) not in assigned and not en.cover:
            out.append({**base, "type": INVALID_ASSIGNMENT, "severity": HIGH,
                        "description": f"{who} is not assigned to {ctx.bn(en.brand_id)} / {ctx.pn(en.process_id)}.",
                        "suggestion": "Add the assignment or mark this as a cover shift."})

    # 3) capacity: distinct brands worked per employee per day
    for (e, d), brands in day_brands.items():
        if emp_dates is not None and (e, d) not in emp_dates:
            continue
        cap = ctx.employees.get(e, {}).get("capacity", 2)
        if len(brands) > cap:
            out.append(dict(date=d, brand_id=None, process_id=None, employee_id=e, type=OVERLOAD, severity=HIGH,
                            description=f"{ctx.en(e)} covers {len(brands)} brands on {d.isoformat()} "
                                        f"(capacity {cap}).",
                            suggestion="Move one brand's work to another employee.", backup_ids=""))

    # 4) soft rule (full validation only): more than 6 consecutive working days
    if full:
        worked = defaultdict(set)
        for en in entries:
            if en.status == W:
                worked[en.employee_id].add(en.date)
        for e, days in worked.items():
            streak, prev = 0, None
            for d in sorted(days):
                streak = streak + 1 if prev and d - prev == timedelta(days=1) else 1
                if streak == MAX_CONSECUTIVE_DAYS + 1:
                    out.append(dict(date=d, brand_id=None, process_id=None, employee_id=e,
                                    type=CONSECUTIVE_WORK, severity=LOW,
                                    description=f"{ctx.en(e)} works more than {MAX_CONSECUTIVE_DAYS} days in a row "
                                                f"(from {d.isoformat()}).",
                                    suggestion="Add a rest day or a backup for this stretch.", backup_ids=""))
                prev = d
    return out


# ---- statistics ------------------------------------------------------------
def coverage_stats(ctx: Context, entries: List[Entry], dates: List[date]) -> dict:
    cov = _valid_working(ctx, entries)
    per_brand = defaultdict(lambda: [0, 0])
    per_process = defaultdict(lambda: [0, 0])
    total_req = total_ok = 0
    for d in dates:
        for (b, p), rule in ctx.rules.items():
            if not is_operational(ctx, b, p, d):
                continue
            need = rule["min_staff"]
            ok = min(need, len(cov.get((b, p, d), set())))
            total_req += need; total_ok += ok
            per_brand[b][0] += need; per_brand[b][1] += ok
            per_process[p][0] += need; per_process[p][1] += ok
    pct = lambda ok, req: round(100 * ok / req, 1) if req else 100.0
    return dict(
        required=total_req, covered=total_ok, percent=pct(total_ok, total_req),
        per_brand={b: dict(required=r, covered=c, percent=pct(c, r)) for b, (r, c) in per_brand.items()},
        per_process={p: dict(required=r, covered=c, percent=pct(c, r)) for p, (r, c) in per_process.items()},
    )
