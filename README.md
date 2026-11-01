# Smart Roster Management System

Automatic monthly (and weekly-view) employee rosters for multi-brand operations teams, with
explainable conflict detection and instant re-validation. Aqua-blue dashboard, FastAPI backend, SQLite by default.

## Run it (2 minutes)

Requires Python 3.10+.

```bash
# macOS / Linux
./run.sh

# Windows
run.bat
```

Open **http://localhost:8000**. On first start the app creates `backend/roster.db` and loads sample data
(32 employees, 5 pods, 25 brands, 4 processes, holidays, leaves) and generates this month's and next month's rosters.
Interactive API docs: http://localhost:8000/docs

Manual start:

```bash
cd backend
python -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

## Run the tests

```bash
python -m unittest discover -s tests -v
```

The scheduling and validation engine (`backend/app/engine.py`) has no framework dependencies, so these tests
need nothing installed.

## Deploy publicly

Step-by-step Vercel + Neon (PostgreSQL) guide: [`DEPLOY_VERCEL.md`](DEPLOY_VERCEL.md).

## What to try first

1. **Dashboard** - KPIs, charts, brands needing attention (all from the database).
2. **Roster Planner** - switch **Weekly / Monthly**, filter by pod/brand/process, click a cell to edit it.
3. **Conflicts** - open a coverage gap, see the reason and one-click backup suggestions.
4. **Leave Management** - approve a *Pending* leave; the app shows exactly which roster cells changed and the new gaps.

Full walkthrough, architecture, API list, deployment and the answers to the assessment's README questions are in
[`docs/IMPLEMENTATION_GUIDE.md`](docs/IMPLEMENTATION_GUIDE.md).

## Layout

```
backend/app/engine.py     pure scheduling + validation engine (tested)
backend/app/services.py   loads DB -> engine, saves rosters/conflicts, dashboard + report data
backend/app/models.py     SQLAlchemy models (14 tables)
backend/app/main.py       FastAPI routes (/api/...) and static file hosting
backend/app/seed.py       sample company data
public/                   index.html, styles.css, app.js (no build step)
tests/test_engine.py      scenario tests
```


## Design and Approach

The system uses a relational database to manage employees, brands, processes, and pods. Employees are assigned to pods, brands are linked to pods, and each brand has its own processes and working days. This structure helps maintain clear relationships between different records and makes data management easier.

The roster is generated using a rule-based approach that considers employee availability, brand working days, holidays, process requirements, and staffing needs. After generation, the system validates the roster to check whether all required conditions are satisfied and identifies conflicts or missing employee coverage.

The system supports both single-resource and multi-resource brands. In single-resource brands, one employee handles all assigned processes, while in multi-resource brands, multiple employees share the responsibilities. If an employee is unavailable on a required working day, the system identifies the affected assignments, highlights the coverage gap, and suggests available backup employees.

The system also detects issues such as leave conflicts, weekly-off conflicts, insufficient staffing, missing process coverage, and workload limits. These conflicts are displayed with their reasons and severity so that managers can review and resolve them. The system automates roster generation, availability checks, conflict detection, validation, and backup suggestions, while important decisions such as leave approval, backup selection, manual roster changes, and final publishing remain under manager control.

The application can be further improved to support larger teams and more brands by using database indexing, better data handling, and advanced scheduling algorithms such as Google OR-Tools. Other possible improvements include role-based login, activity logs, better testing with larger datasets, and shift-based scheduling. These changes would make the system more efficient, flexible, and suitable for larger teams.