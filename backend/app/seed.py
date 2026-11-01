"""
Sample data: 32 employees, 5 pods, 25 brands (20 single-resource = 80%, 5 multi-resource),
4 processes, mixed calendars, weekly offs, leaves and public holidays.
Run standalone with:  python -m app.seed   (from the backend folder)  - or use Settings > Reset demo data.
"""
from datetime import date

from . import engine as E
from . import services
from .models import (Assignment, Base, Brand, Conflict, Employee, Holiday, Leave, Pod, Process, Roster,
                     RosterEntry, SessionLocal, WeeklyOff, WorkingRule, engine)

NAMES = ["Rahul Mehta", "Priya Nair", "Sneha Kulkarni", "Amit Verma", "Neha Kapoor", "Riya Sharma", "Arjun Rao",
         "Kavya Iyer", "Rohan Gupta", "Ananya Das", "Vikram Singh", "Pooja Patel", "Karan Malhotra", "Divya Menon",
         "Sahil Khan", "Isha Joshi", "Manish Yadav", "Tanya Bose", "Nikhil Jain", "Aditi Rane", "Varun Chopra",
         "Meera Pillai", "Harsh Vora", "Simran Kaur", "Yash Thakur", "Lata Reddy", "Gaurav Sinha", "Jyoti Mishra",
         "Faisal Ansari", "Bhavna Shah", "Deepak Nambiar", "Swati Desai"]

BRANDS = ["Glowberry Skincare", "UrbanThread", "NutriNest", "PetPals", "Kaffeine Co", "BloomBox", "TrailMate",
          "HomeHaven", "SipSmart", "ZenLeaf Tea", "Craftly", "FitFuel", "LunaLoom", "BrewBuddy", "SnuggleBee",
          "PureRoots", "GadgetGully", "StyleSutra", "SpiceRoute", "Mintly",           # single-resource (20)
          "Aurora Beauty", "Velvet Vogue", "FreshCart", "Nomad Gear", "KidoKingdom"]  # multi-resource (5)

PROCESSES = [("CS", "Customer Support"), ("ACC", "Abandoned Cart Conversion"), ("NDR", "Non-Delivery Report"),
             ("Retention", "Customer Retention")]

HOLIDAYS = [("2026-01-26", "Republic Day"), ("2026-03-04", "Holi"), ("2026-08-15", "Independence Day"),
            ("2026-10-02", "Gandhi Jayanti"), ("2026-10-20", "Dussehra"), ("2026-11-08", "Diwali"),
            ("2026-11-24", "Guru Nanak Jayanti"), ("2026-12-25", "Christmas"), ("2027-01-26", "Republic Day")]

SINGLE_PROCESS_SETS = [[0], [0, 1], [0, 1, 2], [0, 2], [0, 3], [0, 1, 3], [0, 1, 2, 3], [0, 2, 3]]


def reset(db):
    for m in (Conflict, RosterEntry, Roster, Leave, WeeklyOff, Assignment, WorkingRule, Holiday, Brand, Employee,
              Pod, Process):
        db.query(m).delete()
    db.commit()


def seed(db, with_rosters=True):
    reset(db)
    pods = [Pod(name=n) for n in ("Alpha Pod", "Bravo Pod", "Charlie Pod", "Delta Pod", "Echo Pod")]
    db.add_all(pods)
    procs = [Process(name=n, description=d) for n, d in PROCESSES]
    db.add_all(procs)
    db.flush()

    emps = []
    for i, name in enumerate(NAMES):
        e = Employee(code=f"EMP{i + 1:03d}", name=name, email=f"{name.split()[0].lower()}@example.com",
                     pod_id=pods[i % 5].id, status="ACTIVE", daily_capacity=2)
        emps.append(e)
    db.add_all(emps)
    db.flush()
    for k, pod in enumerate(pods):                      # first employee of each pod is the pod lead
        pod.lead_id = emps[k].id

    # default weekly off = Sunday; a few staggered for the multi-resource brands
    offs = {i: 6 for i in range(len(emps))}
    offs.update({20: 2, 21: 4, 23: 2, 24: 0, 28: 1, 29: 3})
    for i, wd in offs.items():
        db.add(WeeklyOff(employee_id=emps[i].id, weekday=wd))

    brands = [Brand(name=n, status="ACTIVE", pod_id=pods[i % 5].id) for i, n in enumerate(BRANDS)]
    db.add_all(brands)
    db.flush()

    def rule(bi, pi, cal, mn=1):
        db.add(WorkingRule(brand_id=brands[bi].id, process_id=procs[pi].id, calendar_type=cal, min_staff=mn))

    def assign(ei, bi, pi):
        db.add(Assignment(employee_id=emps[ei].id, brand_id=brands[bi].id, process_id=procs[pi].id))

    # --- 20 single-resource brands: one employee handles every process of the brand
    for bi in range(20):
        ei = bi if bi < 19 else 18                      # employee 18 handles brands 18 AND 19 (multi-brand)
        cal = E.CAL_SUNDAY_HOLIDAY_OFF
        if bi == 0:
            cal = E.CAL_365                             # demo: 365-day brand, only employee has Sunday off
        if bi == 7:
            cal = E.CAL_HOLIDAY_OFF                     # demo: Sunday-open brand with Sunday-off employee
        for pi in SINGLE_PROCESS_SETS[bi % len(SINGLE_PROCESS_SETS)]:
            rule(bi, pi, cal)
            assign(ei, bi, pi)

    # --- 5 multi-resource brands
    # 20: three people share CS+ACC (ACC needs 2 people), 365 days
    for pi, mn in ((0, 1), (1, 2)):
        rule(20, pi, E.CAL_365, mn)
        for ei in (19, 20, 21):
            assign(ei, 20, pi)
    assign(25, 20, 0)                                   # floater from another brand overlaps on CS
    # 21: three people, overlapping processes, 365 days
    for pi, who in ((0, (22, 23)), (1, (23, 24)), (2, (24, 22))):
        rule(21, pi, E.CAL_365)
        for ei in who:
            assign(ei, 21, pi)
    # 22: two people, separate processes, closed Sundays + holidays
    rule(22, 0, E.CAL_SUNDAY_HOLIDAY_OFF); assign(25, 22, 0)
    rule(22, 1, E.CAL_SUNDAY_HOLIDAY_OFF); assign(26, 22, 1)
    # 23: three people share Retention (+CS for two), 365 days
    rule(23, 3, E.CAL_365)
    for ei in (27, 28, 29):
        assign(ei, 23, 3)
    rule(23, 0, E.CAL_365)
    for ei in (27, 28):
        assign(ei, 23, 0)
    # 24: two people, separate processes, Sunday + holiday closed
    rule(24, 0, E.CAL_SUNDAY_HOLIDAY_OFF); assign(30, 24, 0)
    rule(24, 2, E.CAL_SUNDAY_HOLIDAY_OFF); assign(31, 24, 2)

    for d, n in HOLIDAYS:
        db.add(Holiday(date=date.fromisoformat(d), name=n))

    t = date.today()
    y, m = t.year, t.month

    def day(n):
        return date(y, m, min(n, 28))

    db.add_all([
        Leave(employee_id=emps[3].id, start_date=day(18), end_date=day(19), leave_type="Casual",
              reason="Family function", status="APPROVED"),
        Leave(employee_id=emps[20].id, start_date=day(16), end_date=day(17), leave_type="Sick",
              reason="Fever", status="APPROVED"),
        Leave(employee_id=emps[10].id, start_date=day(25), end_date=day(26), leave_type="Casual",
              reason="Travel", status="PENDING"),
        Leave(employee_id=emps[5].id, start_date=day(23), end_date=day(24), leave_type="Comp-off",
              reason="Worked on a holiday", status="PENDING"),
        Leave(employee_id=emps[8].id, start_date=day(9), end_date=day(9), leave_type="Casual",
              reason="Personal", status="REJECTED"),
    ])
    db.commit()
    if with_rosters:
        services.generate_roster(db, m, y)
        ny, nm = (y + 1, 1) if m == 12 else (y, m + 1)
        services.generate_roster(db, nm, ny)


if __name__ == "__main__":
    Base.metadata.create_all(engine)
    with SessionLocal() as session:
        seed(session)
    print("Seeded demo data.")
