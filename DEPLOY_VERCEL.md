# Deploy Smart Roster to Vercel (public link)

Total time: ~15 minutes. Cost: free (Vercel Hobby + Neon free tier).

**How it works on Vercel**

| Part | Where it runs |
|---|---|
| `public/` (HTML, CSS, JS) | Vercel CDN, served at `/` |
| `index.py` -> `backend/app/main.py` (FastAPI, `/api/...`, `/docs`) | Vercel Python serverless function |
| Data | Hosted PostgreSQL (Neon). **SQLite cannot be used on Vercel**: the filesystem is read-only/ephemeral. |

---

## Step 1 - Create a free PostgreSQL database (Neon)

1. Go to https://neon.tech and sign up (GitHub login works).
2. Create a project (any name, e.g. `smart-roster`). Pick the region closest to your users
   (for India: *Asia Pacific - Singapore*).
3. On the project dashboard click **Connect**, tick **Connection pooling**, and copy the connection string:

   ```
   postgresql://neondb_owner:xxxx@ep-xxxx-pooler.ap-southeast-1.aws.neon.tech/neondb?sslmode=require
   ```

   Keep it private. It is a password.

## Step 2 - Load the demo data into that database (one time, from your computer)

Serverless functions must not create tables / seed on every cold start, so you do it once yourself.

**Windows (PowerShell):**
```powershell
cd smart-roster\backend
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
$env:DATABASE_URL = "PASTE_YOUR_NEON_URL_HERE"
python -m app.seed
```

**macOS / Linux:**
```bash
cd smart-roster/backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
DATABASE_URL="PASTE_YOUR_NEON_URL_HERE" python -m app.seed
```

You should see `Seeded demo data.` Re-running it wipes and reloads the demo data.

## Step 3 - Push the project to GitHub

The project already points at `https://github.com/Apoo014/smart-roster.git`.

```bash
cd smart-roster
git add -A
git commit -m "Prepare for Vercel deployment"
git push origin main
```

Do **not** commit `.env`, `roster.db` or `.venv` (the included `.gitignore` already excludes them).

## Step 4 - Import the repo into Vercel

1. Go to https://vercel.com and sign up with GitHub.
2. **Add New... -> Project -> Import** your `smart-roster` repository.
3. Settings on the import screen:
   - **Framework Preset:** FastAPI (or *Other* if FastAPI is not listed)
   - **Root Directory:** leave as `./`
   - **Build / Output / Install commands:** leave empty/default
4. Open **Environment Variables** and add:

   | Name | Value |
   |---|---|
   | `DATABASE_URL` | the Neon connection string from Step 1 |

5. Click **Deploy**. Wait ~1 minute.

> Shortcut: in your Vercel project go to **Storage -> Create -> Neon** and it adds `DATABASE_URL`/`POSTGRES_URL`
> to the project for you. You still need to run Step 2 once, using that URL.

## Step 5 - Check it works

Open the `https://smart-roster-xxxx.vercel.app` link Vercel gives you, then also:

- `/api/health` -> `{"status":"ok"}`
- `/api/dashboard` -> JSON with KPIs
- `/docs` -> interactive API docs

Click through Dashboard, Roster Planner, Conflicts, Leave Management and press **Generate Roster** once.

## Step 6 - Custom name / domain (optional)

Vercel project -> **Settings -> Domains**. You can rename the free subdomain (e.g. `smart-roster.vercel.app`)
or attach your own domain.

## Updating later

Every `git push` to `main` redeploys automatically; pull requests get their own preview URLs.

---

## Alternative: deploy from the command line

```bash
npm i -g vercel
cd smart-roster
vercel login
vercel                      # first deploy (preview)
vercel env add DATABASE_URL # paste the Neon URL, select Production
vercel --prod               # public production deploy
```

## Troubleshooting

| Symptom | Fix |
|---|---|
| `relation "employees" does not exist` / dashboard 500 | You skipped Step 2 (or seeded a different database). Run the seed with the same `DATABASE_URL` that Vercel uses. |
| `DATABASE_URL must be configured on Vercel` | Add the env var in Project -> Settings -> Environment Variables, then **Redeploy**. |
| Deploy log: `No module named psycopg2` | Make sure `requirements.txt` in the repo root contains `psycopg2-binary`. |
| First request is slow (2-5 s) | Normal serverless cold start (and Neon waking up). |
| Dashboard empty after the month changes | The seed only generates this month and next. Press **Generate Roster** for the new month. |
| Function timeout on *Settings -> Reset demo data* | Resetting writes thousands of rows; run `python -m app.seed` locally instead (Step 2). |
| `Connection refused` / SSL errors | The URL must end with `?sslmode=require`. |

## Before you share the link widely

This is a demo app: **there is no login**, so anyone with the link can edit data or press *Reset demo data*.
For a real team, add authentication (e.g. an API key/header check or an auth provider) before sharing publicly.
