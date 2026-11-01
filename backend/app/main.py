from contextlib import asynccontextmanager
from datetime import date
from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from . import engine as E
from . import services
from .models import (Assignment, Base, Brand, Conflict, Employee, Holiday, Leave, Pod, Process, Roster,
                     RosterEntry, SessionLocal, WeeklyOff, WorkingRule, engine, get_db)
from .seed import seed

FRONTEND = Path(__file__).resolve().parents[2] / "frontend"


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(engine)
    with SessionLocal() as db:
        if db.query(Employee).count() == 0:
            seed(db)
    yield


app = FastAPI(title="Smart Roster Management System", version="1.0.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
api = APIRouter(prefix="/api")


# ------------------------------------------------------------------ schemas
class EmployeeIn(BaseModel):
    name: str = Field(min_length=1)
    email: Optional[str] = None
    pod_id: Optional[int] = None
    status: str = "ACTIVE"
    weekly_offs: List[int] = []
    daily_capacity: int = Field(default=2, ge=1, le=6)


class PodIn(BaseModel):
    name: str = Field(min_length=1)
    lead_id: Optional[int] = None
    member_ids: Optional[List[int]] = None


class BrandIn(BaseModel):
    name: str = Field(min_length=1)
    status: str = "ACTIVE"
    pod_id: Optional[int] = None


class ProcessIn(BaseModel):
    name: str = Field(min_length=1)
    description: Optional[str] = None


class AssignmentIn(BaseModel):
    employee_id: int
    brand_id: int
    process_id: int


class RuleIn(BaseModel):
    brand_id: int
    process_id: int
    calendar_type: str = E.CAL_SUNDAY_HOLIDAY_OFF
    min_staff: int = Field(default=1, ge=0, le=20)


class LeaveIn(BaseModel):
    employee_id: int
    start_date: date
    end_date: date
    leave_type: str = "Casual"
    reason: Optional[str] = None


class HolidayIn(BaseModel):
    date: date
    name: str


class GenerateIn(BaseModel):
    month: int = Field(ge=1, le=12)
    year: int = Field(ge=2000, le=2100)
    force: bool = False
    keep_manual: bool = True


class EntryPatch(BaseModel):
    status: str


class PublishIn(BaseModel):
    force: bool = False


class CoverIn(BaseModel):
    employee_id: int


def bad(msg, code=400):
    raise HTTPException(status_code=code, detail=msg)


def need(db, model, id_, label):
    obj = db.get(model, id_)
    if obj is None:
        bad(f"{label} {id_} not found", 404)
    return obj


# ------------------------------------------------------------------ employees
def _employee_rows(db: Session, only: Optional[int] = None):
    pods = {p.id: p.name for p in db.query(Pod).all()}
    brands = {b.id: b.name for b in db.query(Brand).all()}
    procs = {p.id: p.name for p in db.query(Process).all()}
    assigns, offs = {}, {}
    for a in db.query(Assignment).all():
        assigns.setdefault(a.employee_id, []).append(a)
    for w in db.query(WeeklyOff).all():
        offs.setdefault(w.employee_id, []).append(w.weekday)
    q = db.query(Employee)
    if only:
        q = q.filter(Employee.id == only)
    out = []
    for e in q.order_by(Employee.id).all():
        al = assigns.get(e.id, [])
        out.append(dict(id=e.id, code=e.code, name=e.name, email=e.email, status=e.status, pod_id=e.pod_id,
                        pod=pods.get(e.pod_id), daily_capacity=e.daily_capacity,
                        weekly_offs=sorted(offs.get(e.id, [])),
                        weekly_off_names=[E.WEEKDAYS[d] for d in sorted(offs.get(e.id, []))],
                        brands=sorted({brands[a.brand_id] for a in al if a.brand_id in brands}),
                        brand_ids=sorted({a.brand_id for a in al}),
                        processes=sorted({procs[a.process_id] for a in al if a.process_id in procs})))
    return out


def _set_weekly_offs(db, emp_id, days):
    db.query(WeeklyOff).filter(WeeklyOff.employee_id == emp_id).delete()
    for d in sorted(set(days)):
        if not 0 <= d <= 6:
            bad("weekly_offs must be numbers 0 (Mon) to 6 (Sun)")
        db.add(WeeklyOff(employee_id=emp_id, weekday=d))


@api.get("/employees")
def list_employees(db: Session = Depends(get_db)):
    return _employee_rows(db)


@api.post("/employees")
def create_employee(body: EmployeeIn, db: Session = Depends(get_db)):
    e = Employee(name=body.name, email=body.email, pod_id=body.pod_id, status=body.status,
                 daily_capacity=body.daily_capacity)
    db.add(e)
    db.flush()
    e.code = f"EMP{e.id:03d}"
    _set_weekly_offs(db, e.id, body.weekly_offs)
    db.commit()
    return _employee_rows(db, e.id)[0]


@api.put("/employees/{emp_id}")
def update_employee(emp_id: int, body: EmployeeIn, db: Session = Depends(get_db)):

    e = need(db, Employee, emp_id, "Employee")

    new_status = body.status.strip().upper()

    # If the employee leaves their current pod
    # or becomes inactive, remove their leadership.
    if e.pod_id is not None and (
        e.pod_id != body.pod_id or new_status != "ACTIVE"
    ):
        old_pod = db.get(Pod, e.pod_id)

        if old_pod and old_pod.lead_id == e.id:
            old_pod.lead_id = None

    e.name = body.name
    e.email = body.email
    e.pod_id = body.pod_id
    e.status = new_status
    e.daily_capacity = body.daily_capacity

    _set_weekly_offs(db, e.id, body.weekly_offs)

    db.commit()

    return _employee_rows(db, e.id)[0]


@api.delete("/employees/{emp_id}")
def deactivate_employee(emp_id: int, db: Session = Depends(get_db)):

    e = need(db, Employee, emp_id, "Employee")

    # Clear leadership when the employee is deactivated.
    if e.pod_id is not None:
        pod = db.get(Pod, e.pod_id)

        if pod and pod.lead_id == e.id:
            pod.lead_id = None

    e.status = "INACTIVE"

    db.commit()

    return dict(
        ok=True,
        message=f"{e.name} deactivated successfully."
    )

# ------------------------------------------------------------------ pods
# ------------------------------------------------------------------ pods

@api.get("/pods")
def list_pods(db: Session = Depends(get_db)):

    pods = db.query(Pod).order_by(Pod.id).all()
    employees = db.query(Employee).order_by(Employee.name).all()
    brands = db.query(Brand).all()

    pod_names = {
        p.id: p.name for p in pods
    }

    result = []

    for p in pods:

        # Find the current leader.
        lead = next(
            (e for e in employees if e.id == p.lead_id),
            None
        )

        # A valid leader must be active and belong to this pod.
        valid_lead = (
            lead
            if lead
            and lead.status == "ACTIVE"
            and lead.pod_id == p.id
            else None
        )

        # Display every employee, not just pod members.
        employee_list = []

        for e in employees:

            employee_list.append({
                "id": e.id,
                "code": e.code,
                "name": e.name,
                "status": e.status,
                "pod_id": e.pod_id,
                "pod_name": pod_names.get(e.pod_id),
                "included": e.pod_id == p.id
            })

        result.append({

            "id": p.id,
            "name": p.name,

            "lead_id": valid_lead.id if valid_lead else None,
            "lead": valid_lead.name if valid_lead else None,

            "employee_count": sum(
                1 for e in employees
                if e.pod_id == p.id and e.status == "ACTIVE"
            ),

            "employees": employee_list,

            "brands": sorted(
                b.name for b in brands if b.pod_id == p.id
            )
        })

    return result


# ---------------------------------------------------------
# Helper: Update pod membership and validate its leader
# ---------------------------------------------------------

def apply_pod_membership(db: Session, pod: Pod, body: PodIn):

    if body.member_ids is not None:

        selected_ids = set(body.member_ids)

        employees = db.query(Employee).all()

        employee_map = {
            e.id: e for e in employees
        }

        # Validate employee IDs.
        missing_ids = selected_ids - set(employee_map.keys())

        if missing_ids:
            bad("One or more selected employees do not exist.")

        # Do not allow an employee to belong to two pods.
        for emp_id in selected_ids:

            employee = employee_map[emp_id]

            if employee.pod_id not in (None, pod.id):

                bad(
                    f"{employee.name} already belongs to "
                    f"another pod."
                )

        # Remove employees who are no longer selected.
        for employee in employees:

            if (
                employee.pod_id == pod.id
                and employee.id not in selected_ids
            ):
                employee.pod_id = None

            # Add selected employees to this pod.
            elif employee.id in selected_ids:

                employee.pod_id = pod.id

    # Validate the selected pod leader.
    if body.lead_id is not None:

        lead = db.get(Employee, body.lead_id)

        if not lead:
            bad("Selected pod leader does not exist.")

        if lead.status != "ACTIVE":
            bad("Only active employees can become pod leaders.")

        if lead.pod_id != pod.id:
            bad("Pod leader must belong to this pod.")

    pod.lead_id = body.lead_id


# ---------------------------------------------------------
# Create Pod
# ---------------------------------------------------------

@api.post("/pods")
def create_pod(body: PodIn, db: Session = Depends(get_db)):

    if db.query(Pod).filter(Pod.name == body.name).first():
        bad("A pod with this name already exists.")

    pod = Pod(name=body.name)

    db.add(pod)
    db.flush()

    apply_pod_membership(db, pod, body)

    db.commit()

    return {
        "id": pod.id,
        "message": "Pod created successfully."
    }


# ---------------------------------------------------------
# Update Pod
# ---------------------------------------------------------

@api.put("/pods/{pod_id}")
def update_pod(pod_id: int, body: PodIn, db: Session = Depends(get_db)):

    pod = need(db, Pod, pod_id, "Pod")

    duplicate = db.query(Pod).filter(
        Pod.name == body.name,
        Pod.id != pod_id
    ).first()

    if duplicate:
        bad("A pod with this name already exists.")

    pod.name = body.name

    apply_pod_membership(db, pod, body)

    db.commit()

    return {
        "id": pod.id,
        "message": "Pod updated successfully."
    }

@api.post("/pods")
def create_pod(body: PodIn, db: Session = Depends(get_db)):
    if db.query(Pod).filter(Pod.name == body.name).first():
        bad("A pod with this name already exists")
    p = Pod(name=body.name, lead_id=body.lead_id)
    db.add(p)
    db.commit()
    return dict(id=p.id)


@api.put("/pods/{pod_id}")
def update_pod(pod_id: int, body: PodIn, db: Session = Depends(get_db)):
    p = need(db, Pod, pod_id, "Pod")
    p.name, p.lead_id = body.name, body.lead_id
    db.commit()
    return dict(id=p.id)


# ------------------------------------------------------------------ brands / processes / rules
@api.get("/brands")
def list_brands(db: Session = Depends(get_db)):
    pods = {p.id: p.name for p in db.query(Pod).all()}
    procs = {p.id: p.name for p in db.query(Process).all()}
    emps = {e.id: e.name for e in db.query(Employee).all()}
    rules, people = {}, {}
    for r in db.query(WorkingRule).all():
        rules.setdefault(r.brand_id, []).append(dict(process_id=r.process_id, process=procs.get(r.process_id),
                                                     calendar_type=r.calendar_type, min_staff=r.min_staff))
    for a in db.query(Assignment).all():
        people.setdefault(a.brand_id, set()).add(a.employee_id)
    return [dict(id=b.id, name=b.name, status=b.status, pod_id=b.pod_id, pod=pods.get(b.pod_id),
                 employee_count=len(people.get(b.id, ())),
                 employees=sorted(emps[i] for i in people.get(b.id, ()) if i in emps),
                 structure="Single-resource" if len(people.get(b.id, ())) <= 1 else "Multi-resource",
                 rules=sorted(rules.get(b.id, []), key=lambda r: r["process_id"]))
            for b in db.query(Brand).order_by(Brand.name).all()]


@api.post("/brands")
def create_brand(body: BrandIn, db: Session = Depends(get_db)):
    if db.query(Brand).filter(Brand.name == body.name).first():
        bad("A brand with this name already exists")
    b = Brand(name=body.name, status=body.status, pod_id=body.pod_id)
    db.add(b)
    db.commit()
    return dict(id=b.id)


@api.put("/brands/{brand_id}")
def update_brand(brand_id: int, body: BrandIn, db: Session = Depends(get_db)):
    b = need(db, Brand, brand_id, "Brand")
    b.name, b.status, b.pod_id = body.name, body.status, body.pod_id
    db.commit()
    return dict(id=b.id)


@api.get("/processes")
def list_processes(db: Session = Depends(get_db)):
    return [dict(id=p.id, name=p.name, description=p.description) for p in db.query(Process).order_by(Process.id)]


@api.post("/processes")
def create_process(body: ProcessIn, db: Session = Depends(get_db)):
    if db.query(Process).filter(Process.name == body.name).first():
        bad("A process with this name already exists")
    p = Process(name=body.name, description=body.description)
    db.add(p)
    db.commit()
    return dict(id=p.id)


@api.put("/rules")
def upsert_rule(body: RuleIn, db: Session = Depends(get_db)):
    if body.calendar_type not in E.CALENDAR_TYPES:
        bad(f"calendar_type must be one of {', '.join(E.CALENDAR_TYPES)}")
    need(db, Brand, body.brand_id, "Brand")
    need(db, Process, body.process_id, "Process")
    r = db.query(WorkingRule).filter_by(brand_id=body.brand_id, process_id=body.process_id).first()
    if r is None:
        r = WorkingRule(brand_id=body.brand_id, process_id=body.process_id)
        db.add(r)
    r.calendar_type, r.min_staff = body.calendar_type, body.min_staff
    db.commit()
    return dict(ok=True, message="Rule saved. Re-generate the roster to apply it.")


@api.delete("/rules")
def delete_rule(brand_id: int, process_id: int, db: Session = Depends(get_db)):
    db.query(Assignment).filter_by(brand_id=brand_id, process_id=process_id).delete()
    db.query(WorkingRule).filter_by(brand_id=brand_id, process_id=process_id).delete()
    db.commit()
    return dict(ok=True)


# ------------------------------------------------------------------ assignments
@api.get("/assignments")
def list_assignments(db: Session = Depends(get_db)):
    emps = {e.id: e for e in db.query(Employee).all()}
    pods = {p.id: p.name for p in db.query(Pod).all()}
    brands = {b.id: b.name for b in db.query(Brand).all()}
    procs = {p.id: p.name for p in db.query(Process).all()}
    return [dict(id=a.id, employee_id=a.employee_id, employee=emps[a.employee_id].name,
                 pod=pods.get(emps[a.employee_id].pod_id), brand_id=a.brand_id, brand=brands.get(a.brand_id),
                 process_id=a.process_id, process=procs.get(a.process_id),
                 status=emps[a.employee_id].status)
            for a in db.query(Assignment).order_by(Assignment.brand_id, Assignment.process_id).all()
            if a.employee_id in emps]


@api.post("/assignments")
def create_assignment(body: AssignmentIn, db: Session = Depends(get_db)):
    need(db, Employee, body.employee_id, "Employee")
    need(db, Brand, body.brand_id, "Brand")
    need(db, Process, body.process_id, "Process")
    if db.query(Assignment).filter_by(**body.model_dump()).first():
        bad("This employee is already assigned to that brand and process")
    if not db.query(WorkingRule).filter_by(brand_id=body.brand_id, process_id=body.process_id).first():
        db.add(WorkingRule(brand_id=body.brand_id, process_id=body.process_id,
                           calendar_type=E.CAL_SUNDAY_HOLIDAY_OFF, min_staff=1))
    a = Assignment(**body.model_dump())
    db.add(a)
    db.commit()
    return dict(id=a.id, message="Assignment saved. Re-generate the roster to apply it.")


@api.delete("/assignments/{assignment_id}")
def delete_assignment(assignment_id: int, db: Session = Depends(get_db)):
    a = need(db, Assignment, assignment_id, "Assignment")
    db.delete(a)
    db.commit()
    return dict(ok=True, message="Assignment removed. Re-generate the roster to apply it.")


# ------------------------------------------------------------------ leaves & holidays
def _leave_rows(db, status=None):
    emps = {e.id: e.name for e in db.query(Employee).all()}
    q = db.query(Leave)
    if status:
        q = q.filter(Leave.status == status.upper())
    return [dict(id=l.id, employee_id=l.employee_id, employee=emps.get(l.employee_id), start_date=l.start_date.isoformat(),
                 end_date=l.end_date.isoformat(), days=(l.end_date - l.start_date).days + 1, leave_type=l.leave_type,
                 reason=l.reason, status=l.status) for l in q.order_by(Leave.start_date.desc()).all()]


@api.get("/leaves")
def list_leaves(status: Optional[str] = None, db: Session = Depends(get_db)):
    return _leave_rows(db, status)


@api.post("/leaves")
def create_leave(body: LeaveIn, db: Session = Depends(get_db)):
    need(db, Employee, body.employee_id, "Employee")
    if body.end_date < body.start_date:
        bad("End date cannot be before start date")
    l = Leave(**body.model_dump(), status="PENDING")
    db.add(l)
    db.commit()
    return dict(id=l.id)


@api.post("/leaves/{leave_id}/approve")
def approve_leave(leave_id: int, db: Session = Depends(get_db)):
    l = need(db, Leave, leave_id, "Leave")
    l.status = "APPROVED"
    db.commit()
    impact = services.apply_availability_change(db, l.employee_id, l.start_date, l.end_date)
    return dict(leave_id=l.id, status=l.status, impact=impact)


@api.post("/leaves/{leave_id}/reject")
def reject_leave(leave_id: int, db: Session = Depends(get_db)):
    l = need(db, Leave, leave_id, "Leave")
    was = l.status
    l.status = "REJECTED"
    db.commit()
    impact = services.apply_availability_change(db, l.employee_id, l.start_date, l.end_date) if was == "APPROVED" else None
    return dict(leave_id=l.id, status=l.status, impact=impact)


@api.delete("/leaves/{leave_id}")
def delete_leave(leave_id: int, db: Session = Depends(get_db)):
    l = need(db, Leave, leave_id, "Leave")
    was, emp, s, e = l.status, l.employee_id, l.start_date, l.end_date
    db.delete(l)
    db.commit()
    impact = services.apply_availability_change(db, emp, s, e) if was == "APPROVED" else None
    return dict(ok=True, impact=impact)


@api.get("/holidays")
def list_holidays(db: Session = Depends(get_db)):
    return [dict(id=h.id, date=h.date.isoformat(), name=h.name) for h in db.query(Holiday).order_by(Holiday.date)]


@api.post("/holidays")
def create_holiday(body: HolidayIn, db: Session = Depends(get_db)):
    if db.query(Holiday).filter(Holiday.date == body.date).first():
        bad("A holiday already exists on that date")
    h = Holiday(date=body.date, name=body.name)
    db.add(h)
    db.commit()
    return dict(id=h.id, message="Holiday added. Re-generate the roster to apply it.")


@api.delete("/holidays/{holiday_id}")
def delete_holiday(holiday_id: int, db: Session = Depends(get_db)):
    h = need(db, Holiday, holiday_id, "Holiday")
    db.delete(h)
    db.commit()
    return dict(ok=True)


# ------------------------------------------------------------------ rosters
@api.post("/rosters/generate")
def generate(body: GenerateIn, db: Session = Depends(get_db)):
    try:
        roster = services.generate_roster(db, body.month, body.year, body.force, body.keep_manual)
    except ValueError as ex:
        bad(str(ex), 409)
    return services.roster_summary(db, roster)


@api.get("/rosters")
def list_rosters(db: Session = Depends(get_db)):
    ctx = services.build_context(db)
    return [services.roster_summary(db, r, ctx) for r in db.query(Roster).order_by(Roster.year, Roster.month)]


@api.get("/rosters/by-month")
def roster_by_month(month: int, year: int, db: Session = Depends(get_db)):
    r = services.get_roster(db, month, year)
    if r is None:
        bad("No roster has been generated for this month yet", 404)
    return services.roster_grid(db, r)


@api.patch("/rosters/entries/{entry_id}")
def patch_entry(entry_id: int, body: EntryPatch, db: Session = Depends(get_db)):
    try:
        created = services.edit_entry(db, entry_id, body.status.upper())
    except LookupError as ex:
        bad(str(ex), 404)
    except ValueError as ex:
        bad(str(ex))
    ctx = services.build_context(db)
    return dict(ok=True, new_conflicts=[services.conflict_dict(c, ctx) for c in created])


@api.delete("/rosters/entries/{entry_id}")
def remove_cover(entry_id: int, db: Session = Depends(get_db)):
    try:
        created = services.delete_cover(db, entry_id)
    except ValueError as ex:
        bad(str(ex))
    ctx = services.build_context(db)
    return dict(ok=True, new_conflicts=[services.conflict_dict(c, ctx) for c in created])


@api.get("/rosters/{roster_id}")
def get_one(roster_id: int, db: Session = Depends(get_db)):
    return services.roster_summary(db, need(db, Roster, roster_id, "Roster"))


@api.post("/rosters/{roster_id}/validate")
def validate(roster_id: int, db: Session = Depends(get_db)):
    r = need(db, Roster, roster_id, "Roster")
    services.validate_full(db, r)
    return dict(summary=services.roster_summary(db, r), conflicts=services.list_conflicts(db, r.id))


@api.get("/rosters/{roster_id}/conflicts")
def roster_conflicts(roster_id: int, db: Session = Depends(get_db)):
    need(db, Roster, roster_id, "Roster")
    return services.list_conflicts(db, roster_id)


@api.post("/rosters/{roster_id}/submit")
def submit(roster_id: int, db: Session = Depends(get_db)):
    r = need(db, Roster, roster_id, "Roster")
    r.status = "PENDING_APPROVAL"
    db.commit()
    return services.roster_summary(db, r)


@api.post("/rosters/{roster_id}/publish")
def publish(roster_id: int, body: PublishIn, db: Session = Depends(get_db)):
    r = need(db, Roster, roster_id, "Roster")
    result = services.publish(db, r, body.force)
    return dict(**result, summary=services.roster_summary(db, r))


@api.get("/rosters/{roster_id}/export.csv")
def export(roster_id: int, db: Session = Depends(get_db)):
    r = need(db, Roster, roster_id, "Roster")
    return Response(services.export_csv(db, r), media_type="text/csv",
                    headers={"Content-Disposition": f'attachment; filename="roster_{r.year}_{r.month:02d}.csv"'})


# ------------------------------------------------------------------ conflicts
@api.post("/conflicts/{conflict_id}/acknowledge")
def acknowledge(conflict_id: int, db: Session = Depends(get_db)):
    c = need(db, Conflict, conflict_id, "Conflict")
    c.status = "OPEN" if c.status == "ACKNOWLEDGED" else "ACKNOWLEDGED"
    db.commit()
    return dict(id=c.id, status=c.status, note="Acknowledging does not make the roster valid; the conflict stays counted.")


@api.post("/conflicts/{conflict_id}/apply-backup")
def apply_backup(conflict_id: int, body: CoverIn, db: Session = Depends(get_db)):
    c = need(db, Conflict, conflict_id, "Conflict")
    if c.type != E.COVERAGE_GAP or not (c.brand_id and c.process_id and c.date):
        bad("Backups can only be applied to coverage gaps")
    need(db, Employee, body.employee_id, "Employee")
    created = services.add_cover(db, c.roster_id, body.employee_id, c.brand_id, c.process_id, c.date)
    ctx = services.build_context(db)
    return dict(ok=True, remaining=[services.conflict_dict(x, ctx) for x in created])


# ------------------------------------------------------------------ dashboard / reports / admin
@api.get("/dashboard")
def dashboard(month: Optional[int] = None, year: Optional[int] = None, db: Session = Depends(get_db)):
    t = date.today()
    return services.dashboard(db, month or t.month, year or t.year)


@api.get("/reports")
def reports(month: Optional[int] = None, year: Optional[int] = None, db: Session = Depends(get_db)):
    t = date.today()
    return services.reports(db, month or t.month, year or t.year)


@api.post("/admin/reset-demo")
def reset_demo(db: Session = Depends(get_db)):
    seed(db)
    return dict(ok=True)


@api.get("/health")
def health():
    return dict(status="ok")


app.include_router(api)
if FRONTEND.exists():
    app.mount("/static", StaticFiles(directory=str(FRONTEND)), name="static")

    @app.get("/", include_in_schema=False)
    def index():
        return FileResponse(FRONTEND / "index.html")
