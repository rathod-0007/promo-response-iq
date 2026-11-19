# RxLift

**Which doctors should a pharma sales team call more, and which less?**

RxLift loads prescriber-level activity and prescription data into PostgreSQL, measures how each promotion channel moves prescriptions, recommends where to put the effort, designs and costs an incentive-compensation plan, and serves it all through a web app, Excel and PowerPoint exports, and ready-made **Tableau** and **Power BI** dashboards.

It runs on your own data: upload an extract, match its columns once, and every page, insight and export switches to your data **and your wording** ("Detail visits", "Prescribers", "NBRx"...).

[![RxLift overview](docs/app/overview.png)](demo/RxLift_demo.mp4)

> **Demo video (3 min 12 s):** [`demo/RxLift_demo.mp4`](demo/RxLift_demo.mp4). Click it on GitHub to play it. It walks through the web app, all 11 Tableau sheets and dashboards, and the Power BI report, model and data views. Chapter timings are in [`demo/README.md`](demo/README.md).

## Contents
1. [What is inside](#what-is-inside)
2. [Screenshots](#screenshots) (web app, Tableau, Power BI)
3. [Set it up on a new laptop, step by step](#set-it-up-on-a-new-laptop-step-by-step)
4. [Daily use: start and stop](#daily-use-start-and-stop)
5. [Tableau and Power BI: build and open them](#tableau-and-power-bi-build-and-open-them)
6. [Use your own data](#use-your-own-data)
7. [Tests](#tests)
8. [Troubleshooting](#troubleshooting)
9. [How it works, API and project layout](#how-it-works)

---

## What is inside

| Area | What you get | Where |
|---|---|---|
| **Data model** | PostgreSQL star schema (fact, prescriber, territory and month dimensions) and 14 BI-ready tables | `app/sql/`, `app/bi.py` |
| **Promotion response** | Prescriber fixed-effects log-log regression with adstock carry-over, ROI per channel | `app/modeling.py` |
| **Sales force strategy** | Call optimizer (greedy, by marginal ROI), targeting deciles and segments (Invest, Defend, Develop, Self-serve) | `app/analytics.py`, `app/targeting.py` |
| **Incentive compensation** | Quota (same quarter last year plus growth), attainment, payout curve, what-if plan design | `app/incentive.py` |
| **Business intelligence** | Web dashboards, Excel and PowerPoint exports, **Tableau workbook**, **Power BI project**, CSV pack | `app/bi*.py`, `app/exports.py` |
| **Your own data** | CSV or Excel upload with column mapping, validation and your own labels | `app/uploader.py`, `app/importer.py` |
| **Quality** | 123 automated tests against a real PostgreSQL database | `tests/` |

Built with Python 3.13, FastAPI, SQLAlchemy, pandas, NumPy, PostgreSQL, Vite and Chart.js.

## Screenshots

### Web app
| | |
|---|---|
| ![Overview](docs/app/overview.png)<br>**Overview**: KPIs, trend, key insights | ![Dark theme](docs/app/overview_dark.png)<br>**Dark theme** (toggle at the bottom of the sidebar) |
| ![Response model](docs/app/model.png)<br>**Response model**: elasticities, ROI, carry-over | ![Optimizer](docs/app/optimizer.png)<br>**Optimizer**: re-allocate calls by marginal ROI |
| ![Targeting](docs/app/targeting.png)<br>**Targeting**: deciles and segments | ![Incentive](docs/app/incentive.png)<br>**Incentive comp**: quota, attainment, payout |
| ![Explorer](docs/app/explorer.png)<br>**Prescriber explorer**: search, sort, page | ![Data](docs/app/data.png)<br>**Data & reports**: upload, templates, downloads |
| ![BI connections](docs/app/bi.png)<br>**BI connections**: connection details and one-click Tableau / Power BI downloads | |

### Tableau (9 worksheets, 2 dashboards)
Open `RxLift.twbx` in Tableau Public (free) or Tableau Desktop. The data ships inside the file as extracts, so no database login is needed.

![Tableau dashboard: performance](docs/tableau/10_dashboard_performance.png)
![Tableau dashboard: where to focus and incentive plan](docs/tableau/11_dashboard_focus_and_incentive.png)

| | | |
|---|---|---|
| ![](docs/tableau/01_rx_by_month.png)<br>Rx by month | ![](docs/tableau/02_detail_visits_by_month.png)<br>Detail visits by month | ![](docs/tableau/03_rx_by_state.png)<br>Rx by state |
| ![](docs/tableau/04_rx_by_segment.png)<br>Rx by segment | ![](docs/tableau/05_rx_by_specialty.png)<br>Rx by specialty | ![](docs/tableau/06_roi_by_channel.png)<br>ROI by channel |
| ![](docs/tableau/07_call_index_by_decile.png)<br>Call index by decile | ![](docs/tableau/08_attainment_by_territory.png)<br>Quota attainment by territory | ![](docs/tableau/09_payout_by_territory.png)<br>Incentive payout by territory |

### Power BI (3 report pages, data model with DAX measures)
Open `RxLift.pbip` in Power BI Desktop (free), then **Home > Refresh**.

| | |
|---|---|
| ![](docs/powerbi/1_performance.png)<br>**Performance**: KPI cards (DAX measures), trend, state and segment | ![](docs/powerbi/2_where_to_focus.png)<br>**Where to focus**: ROI by channel, share of Rx vs share of visits, call index |
| ![](docs/powerbi/3_incentive_plan.png)<br>**Incentive plan**: attainment, payout, payout curve | ![](docs/powerbi/4_model_relationships.png)<br>**Model view**: star-schema relationships |
| ![](docs/powerbi/5_data_view.png)<br>**Data view**: the tables loaded from the CSV files | |

---

## Set it up on a new laptop, step by step

These steps assume **Windows 10/11 with PowerShell**. macOS and Linux notes are at the end of this section. Follow them in order; each step says how to check that it worked.

### Step 0: Install the tools (once per laptop)

| Tool | Version | Install (PowerShell) | Check it worked |
|---|---|---|---|
| Git | any recent | `winget install --id Git.Git -e` | `git --version` |
| Python | **3.13** or newer | `winget install --id Python.Python.3.13 -e` | `python --version` |
| Node.js | 20 or newer (22 LTS is fine) | `winget install --id OpenJS.NodeJS.LTS -e` | `node --version` and `npm --version` |
| PostgreSQL | 14 or newer (17 recommended) | `winget install --id PostgreSQL.PostgreSQL.17 -e` | see below |

**Important:** after installing, **close PowerShell and open a new one** so the new programs are found.

PostgreSQL asks you to choose a **password for the `postgres` superuser**. Write it down: you need it in Step 2. Keep port **5432** (the default) and accept the other defaults. To check it, run:

```powershell
& "C:\Program Files\PostgreSQL\17\bin\psql.exe" --version
```

If you installed a different version, change `17` in that path (look inside `C:\Program Files\PostgreSQL`).

For the dashboards (optional, install them later if you only want the web app):

| Tool | Install |
|---|---|
| Tableau Public (free) | `winget install --id Tableau.Public -e` (or download from public.tableau.com) |
| Power BI Desktop (free) | `winget install --id Microsoft.PowerBI -e` (or the Microsoft Store) |

### Step 1: Get the code

```powershell
cd $HOME\Documents
git clone https://github.com/rathod-0007/rxlift.git
cd rxlift
```

The folder `rxlift` is the **project root**. Every later command is run from it unless a step says otherwise.

### Step 2: Create the database (once)

This creates a login `promo` (password `promo`) and a database `promo`, which is what `config.json` expects.

```powershell
& "C:\Program Files\PostgreSQL\17\bin\psql.exe" -U postgres -f scripts/create_database.sql
```

Enter the `postgres` password from Step 0 when asked. You should see `CREATE ROLE` and `CREATE DATABASE`.
If it says `role "promo" already exists`, that is fine: the database was created before. Use a different database or password by setting `DATABASE_URL` (see [Settings](#settings)).

Check the connection:

```powershell
& "C:\Program Files\PostgreSQL\17\bin\psql.exe" "postgresql://promo:promo@localhost:5432/promo" -c "select 1"
```

### Step 3: Start the backend (terminal 1)

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install --upgrade pip
.\.venv\Scripts\python -m pip install -r requirements.txt
.\.venv\Scripts\python -m uvicorn app.main:app --port 8000 --reload
```

Wait until you see `Application startup complete`. The first start creates all tables and loads 600 prescribers x 24 months of built-in synthetic data, which takes a few seconds. Check it in a browser: http://localhost:8000/docs (API documentation) or http://localhost:8000/api/health (should show `ok`).

**Leave this terminal open.** The backend runs as long as this window stays open.

### Step 4: Start the web UI (terminal 2)

Open a **second** PowerShell window:

```powershell
cd $HOME\Documents\rxlift\frontend
npm install
npm run dev
```

Open **http://localhost:5173**. You should see the RxLift overview with KPIs and charts. The dev server forwards `/api` to the backend, so no other setup is needed.

> Shortcut: after the installs in Steps 3 and 4 (`pip install` and `npm install`), `powershell -ExecutionPolicy Bypass -File scripts/dev.ps1` opens both terminals (backend and UI) for you.

### Step 5 (optional): Load the realistic sample data set

Out of the box the app shows built-in synthetic data. To see it on a realistic extract with different column names, text dates, four segments, territories, blanks and duplicates (the same file used for the demo video), open a **third** terminal in the project root:

```powershell
.\.venv\Scripts\python scripts/load_sample_upload.py
```

Refresh the browser. The app now speaks the data set's own wording ("Prescribers", "Detail visits", "State", "Segment"). To return to the built-in data: `.\.venv\Scripts\python scripts/load_sample_upload.py --reset` (or **Data & reports > Restore sample data** in the app).

### Step 6 (optional): Build the Tableau workbook and Power BI project

See [Tableau and Power BI](#tableau-and-power-bi-build-and-open-them) below.

### Step 7 (optional): Run the tests

See [Tests](#tests) below.

### macOS and Linux

The same steps work with these changes:
* Install with Homebrew (`brew install git python@3.13 node postgresql@17`) or your package manager, and start PostgreSQL (`brew services start postgresql@17`).
* Create the database with `psql postgres -f scripts/create_database.sql` (or `sudo -u postgres psql -f scripts/create_database.sql` on Linux).
* Use `python3 -m venv .venv`, then `./.venv/bin/python` instead of `.\.venv\Scripts\python`.
* Power BI Desktop is Windows only. The web app and Tableau Public run on macOS too.

### Settings

Defaults live in `config.json`. Environment variables override them (set them in the same PowerShell window before starting the backend):

| Variable | Purpose | Example |
|---|---|---|
| `DATABASE_URL` | Use another PostgreSQL | `$env:DATABASE_URL="postgresql+psycopg://user:pass@host:5432/dbname"` |
| `DB_SCHEMA` | Schema inside the database (default `public`) | `$env:DB_SCHEMA="rxlift"` |
| `CORS_ORIGINS` | Allowed browser origins (only for a separate front-end host) | |
| `FRONTEND_DIST` | Folder of the built UI (single-process mode) | |
| `VITE_BACKEND_URL` | Where the dev server sends `/api` (default `http://localhost:8000`) | |
| `TEST_DATABASE_URL` | Database the tests use (see [Tests](#tests)) | |

`.env.example` lists the same values.

### Single-process mode (no second terminal)

```powershell
cd frontend
npm install
npm run build
cd ..
.\.venv\Scripts\python -m uvicorn app.main:app --port 8000
```

The backend now also serves the built UI at **http://localhost:8000**.

### Docker (optional)

`docker compose up --build` runs PostgreSQL plus the API with the built UI on http://localhost:8000. The compose file and Dockerfile are included, but they were not run on the development machine (no Docker engine there).

---

## Daily use: start and stop

**Start** (after the first-time setup above):

```powershell
# terminal 1, from the project root
.\.venv\Scripts\python -m uvicorn app.main:app --port 8000 --reload
# terminal 2
cd frontend; npm run dev
```

Then open http://localhost:5173. PostgreSQL starts with Windows as a service, so you do not start it yourself.

**Stop:** press `Ctrl+C` in each terminal.

**Update to the latest code:**

```powershell
git pull
.\.venv\Scripts\python -m pip install -r requirements.txt
cd frontend; npm install
```

---

## Tableau and Power BI: build and open them

Both files are **generated from whatever data set is loaded** (built-in or your upload), so titles, field names and charts follow your own labels, and a chart is only built when its columns exist and carry more than one value. The generated files contain paths from the machine that made them, so they are **not stored in Git**: generate them on the laptop that will open them. Two ways:

### Option A: download from the app (easiest)
1. Start the backend and UI (Steps 3 and 4).
2. Open **BI connections** in the sidebar.
3. Click **Download Tableau workbook** (`RxLift.twbx`) and/or **Download Power BI project** (`RxLift_powerbi.zip`).

The Tableau download needs one extra package: `.\.venv\Scripts\python -m pip install -r requirements-bi.txt`, then restart the backend. Without it the button explains what to install.

### Option B: build from the command line
```powershell
.\.venv\Scripts\python -m pip install -r requirements-bi.txt        # Tableau's Hyper API (once)
.\.venv\Scripts\python scripts/build_tableau.py                     # writes bi\tableau\RxLift.twbx
.\.venv\Scripts\python scripts/build_powerbi.py                     # writes bi\powerbi\RxLift.pbip
```

### Open the Tableau workbook
1. Install Tableau Public (Step 0).
2. Double-click `bi\tableau\RxLift.twbx` (or `File > Open` in Tableau Public). The sheet tabs are along the bottom; the two dashboards are the last two tabs.
3. If Tableau says the workbook is locked or in use, close Tableau fully and re-open the file.

### Open the Power BI project
1. Install Power BI Desktop (Step 0).
2. Double-click `bi\powerbi\RxLift.pbip`.
3. A **"sign in" window may appear. You do not need an account: click Cancel** (or the X).
4. The report opens empty. Click **Home > Refresh** (or **Refresh now** in the yellow bar) and wait about 20 seconds. The three pages (Performance, Where to focus, Incentive plan) fill with data.
5. If you downloaded the zip instead (Option A): unzip it **to `C:\RxLift`** so the data folder is `C:\RxLift\Data`, then open `RxLift.pbip` from there. If you unzip somewhere else, set **Home > Transform data > Edit parameters > DataFolder** to the full path of the `Data` folder, ending with a backslash, e.g. `D:\stuff\RxLift\Data\`.

### What Sisense gets
No Sisense dashboard is built. The same star-schema tables work there through its PostgreSQL connector or the CSV pack (the BI connections page has the steps).

### Connect your own Tableau or Power BI to the database
The **BI connections** page shows the host, port, database and schema, with Copy buttons and step-by-step instructions for Tableau, Power BI and Sisense. A read-only login can be created with:

```powershell
& "C:\Program Files\PostgreSQL\17\bin\psql.exe" -U postgres -d promo -v bi_password="'choose-a-password'" -v schema=public -f scripts/create_bi_user.sql
```

Star schema (views, always current): `bi_fact_hcp_month`, `bi_dim_hcp`, `bi_dim_territory`, `bi_dim_month`, plus a flat `bi_flat_hcp_month`. Analysis tables (published after every upload and on demand): `bi_model_terms`, `bi_channel_roi`, `bi_call_plan`, `bi_targeting_deciles`, `bi_hcp_segment`, `bi_ic_territory_quarter`, `bi_ic_payout_curve`, `bi_dataset_labels`, `bi_refresh_log`.

---

## Use your own data

Upload a CSV or Excel (.xlsx) file on **Data & reports**: one row per prescriber per month. Column **names are free**: you match them to fields, and the app suggests the matches itself. A blank template downloads from the upload card.

| Field | Needed | Notes |
|---|---|---|
| Prescriber ID | yes | any text or number (NPI, account ID...) |
| Month | yes | `2025-01`, `2025-01-15`, `01/2025`, `Jan-2025`, `202501`, Excel dates |
| Prescriptions (volume) | yes | TRx, NBRx, units or sales; not negative |
| Main promotion channel | yes | calls or detail visits; drives the optimizer |
| Second / third channel | no | samples, e-mails...; left out of the analysis if absent or all 0 |
| Prescriber name, region, specialty | no | become filters and breakdowns when they have more than one value |
| Tier / segment | no | any labels (A/B/C, Gold/Silver...); **derived from volume** when absent |
| Territory, rep | no | enables incentive compensation (needs 15+ months) |

What the app does for you, and always tells you about: sums duplicate prescriber-months (or rejects them), handles missing months (treat as 0, exclude those prescribers, or reject), rounds fractional counts, reads `;`/tab-delimited and Latin-1 files, keeps long IDs as text, and reports bad values with **file row numbers**. A failed upload never damages the data already loaded. Limits come from `config.json` (25 MB, 5,000 prescribers, 60 months).

You also name things your way (the volume, the prescriber, each channel, region, tier, territory) and may give the value of one unit and the cost per channel unit; ROI, optimizer and incentive economics use your numbers. Headings, KPIs, chart titles, table columns, insights, Excel sheets, the PowerPoint, and the Tableau and Power BI files all use these names.

The realistic test file is `samples/lipidex_prescriber_extract.csv` (`scripts/make_sample_upload.py` regenerates it).

---

## Tests

The tests run against a real PostgreSQL, in a throw-away schema that is dropped afterwards, so your data is never touched.

```powershell
$env:TEST_DATABASE_URL = "postgresql+psycopg://promo:promo@localhost:5432/promo"
.\.venv\Scripts\python -m pytest -q
```

Expected: `123 passed`. The Tableau checks need `requirements-bi.txt` installed; without it they are skipped, not failed.

---

## Troubleshooting

| Problem | Fix |
|---|---|
| `python`, `git`, `node` or `psql` is "not recognized" | Close PowerShell and open a new window after installing. For `psql`, use the full path shown in Step 0. |
| `password authentication failed for user "promo"` | Step 2 was not run, or you changed the password. Re-run Step 2, or set `DATABASE_URL` to your own login. |
| `connection refused` on port 5432 | PostgreSQL is not running: open **Services**, start `postgresql-x64-17`. If PostgreSQL uses another port, put it in `DATABASE_URL`. |
| `role "promo" already exists` | Safe to ignore; run only `CREATE DATABASE promo OWNER promo;` if the database is missing. |
| Port 8000 or 5173 already in use | Stop the other program, or use another port: `--port 8001` for the backend and set `$env:VITE_BACKEND_URL="http://localhost:8001"` before `npm run dev`. |
| The page is blank or shows API errors | The backend (terminal 1) is not running. Check http://localhost:8000/api/health. |
| `pip install` fails building a package | Use Python **3.13** (`python --version`). The pinned pandas/numpy versions need a recent Python. |
| Tableau download says to install a package | `.\.venv\Scripts\python -m pip install -r requirements-bi.txt`, then restart the backend. |
| Tableau: file is locked | Close Tableau Public completely (also check Task Manager for `hyperd`), then open the file again. |
| Power BI opens empty / "(Blank)" cards | Click **Home > Refresh**. If it says it cannot find the files, set the `DataFolder` parameter (see above). |
| Power BI asks to sign in | Click **Cancel**. No account is needed for this project. |

---

## How it works

1. **Data** is stored in PostgreSQL (`hcp`, `rx`, `activity`, optional `territory`) plus a profile of the loaded data set (labels, channels, economics).
2. **Model:** each prescriber's volume is regressed on log-transformed channel activity with prescriber fixed effects. Each channel's carry-over (adstock) is chosen by a grid search; coefficients are elasticities, with confidence intervals. ROI per channel uses the elasticity, the value of a unit and the cost per unit.
3. **Optimizer:** greedy allocation of the main channel's monthly budget to the prescribers where the response curve is steepest; shows the gain from re-allocating at the same budget, or from a +/- budget change.
4. **Targeting:** prescribers are ranked into deciles by volume and compared with where the effort goes (call index); response-based segments (Invest, Defend, Develop, Self-serve) tell reps what to do.
5. **Incentive compensation:** quota is the same quarter last year plus a growth rate; payout follows a piecewise curve (threshold, 100% at target, accelerator, cap). The plan can be redesigned on the page and the cost of sales recalculated.
6. **BI layer:** the star-schema views and analysis tables are re-published after every upload; the Tableau and Power BI generators read them through `app/bi.py`.

### API
`/api/health`, `/api/meta`, `/api/kpis`, `/api/trend`, `/api/breakdown/{dimension}`, `/api/top-hcps`, `/api/hcps`, `/api/model`, `/api/optimize`, `/api/targeting`, `/api/incentive`, `/api/insights`, `/api/data-info`, `/api/data-dictionary`, `/api/upload/{spec,template,inspect,import}`, `/api/data/reset-sample`, `/api/bi/{info,refresh}`, `/api/export/{xlsx,pptx,bi,tableau,powerbi}`. Filters: `region`, `specialty`, `tier`, `start`, `end` (YYYY-MM). Interactive docs at `/docs`.

### Project layout
```
app/            FastAPI app: config, db, datagen, analytics, modeling, targeting, incentive, uploader,
                importer, profile, bi (+ bi_tableau, bi_powerbi), exports, sql/ (schema and views)
frontend/       Vite + Chart.js single-page UI (src/pages/*.js, src/styles.css)
scripts/        create_database.sql, create_bi_user.sql, build_tableau.py, build_powerbi.py,
                load_sample_upload.py, make_sample_upload.py, dev.ps1
samples/        lipidex_prescriber_extract.csv (realistic upload test file)
tests/          pytest suite (123 tests, real PostgreSQL)
docs/           screenshots used in this README
demo/           RxLift_demo.mp4 (screen recording) and its chapter list
config.json     defaults (database, simulation, model, limits)
```

Tableau Public, Power BI Desktop and Sisense are commercial or third-party tools and are not part of this repository; only the files RxLift generates for them are.
