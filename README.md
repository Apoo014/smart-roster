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
frontend/                 index.html, styles.css, app.js (no build step)
tests/test_engine.py      scenario tests
```
