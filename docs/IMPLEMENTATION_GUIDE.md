# Implementation Guide

## 1. What you get

| Piece | Where | Notes |
|---|---|---|
| Scheduling + validation engine | `backend/app/engine.py` | Pure Python, unit-tested (11 scenarios) |
| Database models | `backend/app/models.py` | 14 tables, SQLite now, PostgreSQL-ready |
| Service layer | `backend/app/services.py` | Connects DB to engine; dashboards, reports, CSV |
| REST API | `backend/app/main.py` | `/api/...`, docs at `/docs` |
| Sample data | `backend/app/seed.py` | 32 employees, 25 brands (20 single-resource = 80%), 5 multi-resource |
| Dashboard | `frontend/` | Aqua-blue/blue theme, weekly + monthly roster, no build step |

**Verification status (be honest in your interview):** the engine and its 11 scenario tests were run and pass.
The FastAPI/SQLAlchemy layer and the browser UI were written to the same contracts and syntax-checked,
but they could not be executed in the environment where this package was built (no package installs).
Run `./run.sh`, click through each page once, and fix anything that surfaces. Expect small
issues, not structural ones.

## 2. How the roster is built (maps to the blueprint's 8 stages)

1. **Input** - `services.build_context()` loads employees, assignments, rules, weekly offs, *approved* leaves, holidays.
2. **Dates** - `engine.month_dates()`.
3. **Requirement** - `engine.is_operational()` applies the brand/process calendar (`365`, `HOLIDAY_OFF`, `SUNDAY_HOLIDAY_OFF`) and `min_staff`.
4. **Eligibility** - an employee is a candidate only through an `Assignment` row, and only if ACTIVE.
5. **Allocation** - `engine.generate_entries()`: every assignee works each open day unless on leave / comp-off / weekly off. Each cell gets a code: `W` working, `O` weekly off, `L` leave, `H` public holiday, `C` comp-off, `X` brand closed (non-holiday Sunday).
6. **Weekly off** - treated as mandatory. If it would leave a required slot uncovered the engine **does not** override it; validation raises a CRITICAL coverage gap with backup suggestions.
7. **Validation** - `engine.compute_conflicts()` checks coverage, leave/weekly-off violations, invalid assignments, capacity (distinct brands per day), and a low-severity "more than 6 days in a row" rule.
8. **Save** - roster stored as `DRAFT` with its conflicts; publishing is blocked while CRITICAL/HIGH conflicts exist unless a manager explicitly overrides.

### Hard vs soft constraints
Hard (always enforced / reported): availability, approved leave, operating calendar coverage, min staffing, assignment eligibility, capacity.
Soft (reported, never blocking): consecutive-days rule today. Workload balance is shown in Reports > Utilization.

### Incremental re-validation (change management)
Approving a leave calls `services.apply_availability_change()`:
1. only that employee's entries inside the leave dates are refreshed (`engine.recompute_statuses`);
2. only the affected `(brand, process, date)` cells and `(employee, date)` pairs are re-validated;
3. the UI shows how many entries changed and any new gaps, each with one-click backup buttons.

Manual cell edits and "Assign backup" use the same scoped validation. Manually edited cells are marked with a dot and survive re-generation.

## 3. Using the dashboard

* **Month picker** (top bar) sets the month for every page. **Generate Roster** builds it.
* **Roster Planner** - `Weekly | Monthly` toggle; in weekly view use *Prev/Next week* (Mon-Sun, clipped to the month). Filters: search, pod, brand, process, "Gaps only". Red-outlined cells are coverage gaps. The bottom row counts employees working per day.
* **Edit a cell** - choose a status; the roster is re-validated and you're told about any new issue. Cover shifts (backup staff) show a blue `cover` tag and can be removed.
* **Publish** - warns if CRITICAL/HIGH conflicts remain; you may override, and the override is recorded on the roster.
* **Acknowledge** on a conflict records that you've seen it. It **never** makes the roster look valid; the conflict stays in the counts.

## 4. Demo script (3-5 min video)

| Time | Show |
|---|---|
| 0:00 | Dashboard: KPIs and charts, "Brands Requiring Attention" |
| 0:30 | Employees, Brands (calendars + min staff), Assignments |
| 1:00 | Roster Planner: Monthly, then Weekly; filter one brand |
| 2:00 | Conflicts: *Glowberry Skincare* (365 days, only employee has Sunday off) - read the explanation |
| 2:45 | Leave Management: approve the pending leave for **Vikram Singh** (sole employee of *Craftly*) - see the impact dialog and gaps |
| 3:30 | Click **Assign <name> as cover** - gap disappears; show the Roster Planner cover row |
| 4:15 | Explain: pure engine, incremental validation, human control over publishing |

## 5. API summary (all under `/api`)

| Area | Endpoints |
|---|---|
| Employees | `GET/POST /employees`, `PUT/DELETE /employees/{id}` (DELETE = deactivate) |
| Pods | `GET/POST /pods`, `PUT /pods/{id}` |
| Brands / processes | `GET/POST /brands`, `PUT /brands/{id}`, `GET/POST /processes` |
| Rules | `PUT /rules` (calendar + min staff), `DELETE /rules` |
| Assignments | `GET/POST /assignments`, `DELETE /assignments/{id}` |
| Leave | `GET/POST /leaves`, `POST /leaves/{id}/approve`, `.../reject`, `DELETE /leaves/{id}` |
| Holidays | `GET/POST /holidays`, `DELETE /holidays/{id}` |
| Rosters | `POST /rosters/generate`, `GET /rosters`, `GET /rosters/by-month?month&year`, `POST /rosters/{id}/validate`, `GET /rosters/{id}/conflicts`, `PATCH/DELETE /rosters/entries/{id}`, `POST /rosters/{id}/submit`, `POST /rosters/{id}/publish`, `GET /rosters/{id}/export.csv` |
| Conflicts | `POST /conflicts/{id}/acknowledge`, `POST /conflicts/{id}/apply-backup` |
| Insight | `GET /dashboard`, `GET /reports`, `POST /admin/reset-demo`, `GET /health` |

## 6. Deploying publicly

**Render (simplest):** push to GitHub, then New > Blueprint > select the repo (`render.yaml` is included).
Free instances sleep and the SQLite file is wiped on redeploy, so for a stable demo create a Render PostgreSQL
database, add `psycopg2-binary` to `requirements.txt`, and set `DATABASE_URL` (see `.env.example`).
The app seeds itself when the database is empty.

**Railway / Heroku-style:** the `Procfile` runs `uvicorn` from the `backend` folder.

Before sharing the link, open the deployed site, visit every page, and generate a roster.

## 7. Answers to the assessment's README questions

1. **Modeling.** `Employee`, `Pod`, `Brand`, `Process` are independent tables. `Assignment(employee, brand, process)` is the many-to-many link, so managers change allocations in the UI, never in code. `WorkingRule(brand, process, calendar, min_staff)` holds the client calendar and coverage requirement; `WeeklyOff`, `Leave`, `Holiday` hold employee/organisation availability. `Roster` -> `RosterEntry` (one row per assignment per day) and `Conflict`.
2. **Generation and checking.** Deterministic rule engine (section 2). Validation is a separate function that works on any set of entries, so generated and hand-edited rosters are judged by the same rules.
3. **Single vs multi-resource.** Same code path. A single-resource brand simply has one candidate per process, so any weekly off or leave on an open day becomes a gap. Multi-resource brands with overlapping processes absorb offs when staggered.
4. **Only employee unavailable.** A CRITICAL `COVERAGE_GAP` is created with the reason ("Rahul (on weekly off)") and ranked backup suggestions (already on the brand, same pod, free that day). Nothing is silently published.
5. **Conflicting requirements.** Weekly offs are never silently overridden. Staffing shortages are reported per brand-process-day with the shortfall. A manager can add a cover shift (which is validated for capacity) or edit the cell (which is flagged as a violation).
6. **Automated vs human.** Automated: generation, validation, impact analysis, backup suggestions. Human: approving leave, choosing a backup, overriding weekly offs, acknowledging conflicts, publishing. Those decisions involve trade-offs about people and clients.
7. **If teams and brands double.** Generation is O(dates x assignments), so it stays fast; move to PostgreSQL, add indexes already defined, paginate the grid, and introduce OR-Tools CP-SAT for fairness-aware allocation (the engine is isolated for that swap).
8. **One more week.** OR-Tools optimisation for automatic backup and weekly-off placement, authentication and roles (pod lead vs manager), the approval workflow with audit log, a leave calendar view, shift timings, and API-level tests with a test database.

## 8. Known limitations

* No login/roles; anyone with the URL can edit. Add auth before real use.
* Shifts are whole days; no time-of-day overlap model.
* Assignment, rule or holiday changes don't auto-update an existing roster; use **Re-generate** (manual edits and cover shifts are preserved).
* Deactivating an employee takes effect on the next generation/validation.
* Sample holidays are illustrative.
* Pod leads are stored as a plain employee id (no foreign key) to avoid a circular reference between pods and employees.
* The consecutive-days check only runs on full validation, not on scoped re-checks.

## 9. Extending

* **Different calendar type:** add a constant in `engine.py`, extend `is_operational()`, add it to `CAL` in `frontend/app.js`.
* **New conflict type:** add a block to `engine.compute_conflicts()` returning a dict with `type`, `severity`, `description`, `suggestion`; the UI lists it automatically.
* **OR-Tools:** write `solve(ctx, dates) -> List[Entry]` and call it in `services.generate_roster()` instead of `generate_entries()`; keep `compute_conflicts()` as the independent checker.
