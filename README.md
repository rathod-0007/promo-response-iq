# RxLift

![Overview](docs/overview.png)

**Which doctors should a pharma sales team call more, and which less?** RxLift loads prescriber-level activity and prescription data into PostgreSQL, measures how each promotion channel moves prescriptions, recommends where to put the effort, designs and costs an incentive-compensation plan, and serves it all through a web app, Excel/PowerPoint exports and BI-ready tables for Tableau, Power BI and Sisense.

It runs on your own data: upload an extract, match its columns once, and every page, insight and export switches to your data **and your wording** ("Detail visits", "Prescribers", "NBRx"...).

## Run it (Python + Node, no Docker needed)

Needs Python 3.13+, Node 20+ and PostgreSQL 14+ (a normal local install is fine).

**1. Database, once**
```powershell
psql -U postgres -f scripts/create_database.sql      # creates login promo / database promo
```
Or point `DATABASE_URL` at any PostgreSQL (see `.env.example`).

**2. Backend, terminal 1** (port 8000)
```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements.txt
.\.venv\Scripts\python -m uvicorn app.main:app --port 8000 --reload
```
The first start creates the tables and loads the built-in synthetic data. API docs: http://localhost:8000/docs

**3. Frontend, terminal 2** (port 5173)
```powershell
cd frontend
npm install
npm run dev
```
Open http://localhost:5173. The dev server proxies `/api` to the backend, so no CORS setup is needed. `scripts/dev.ps1` opens both terminals for you.

**Single process:** `cd frontend; npm run build`, then the backend serves the built UI at http://localhost:8000.

Settings live in `config.json`; environment overrides: `DATABASE_URL`, `DB_SCHEMA`, `CORS_ORIGINS`, `FRONTEND_DIST` (API) and `VITE_BACKEND_URL` (dev proxy).

**Optional, Docker:** `docker compose up --build` runs PostgreSQL plus the API with the built UI on http://localhost:8000 (not exercised in the development environment, which has no Docker engine).

## Where the data comes from
1. **Built-in synthetic data** (default): a seeded generator in `app/datagen.py` with a known ground truth in `config.json`, so the tests can prove the model recovers the true effects.
2. **Your upload**: replaces the data in one all-or-nothing transaction. A failed upload never damages the data already loaded. *Data & reports > Restore sample data* (or `python scripts/load_sample_upload.py --reset`) brings the synthetic data back.

## Use your own data
Upload a CSV or Excel (.xlsx) file on **Data & reports**: one row per prescriber per month. Column **names are free**: you match them to fields, and the app suggests the matches itself.

| Field | Needed | Notes |
|---|---|---|
| Prescriber ID | yes | any text or number (NPI, account ID...) |
| Month | yes | `2025-01`, `2025-01-15`, `01/2025`, `Jan-2025`, `202501`, Excel dates |
| Prescriptions (volume) | yes | TRx, NBRx, units or sales; not negative |
| Main promotion channel | yes | calls or detail visits; drives the optimizer |
| Second / third channel | no | samples, e-mails...; left out of the analysis if absent or all 0 |
| Prescriber name, region, specialty | no | become filters and breakdowns when they have more than one value |
| Tier / segment | no | any labels (A/B/C, Gold/Silver...); **derived from volume** when absent (shares in `config.json`) |
| Territory, rep | no | enables incentive compensation (needs 15+ months) |

What the app does for you, and always tells you about: sums duplicate prescriber-months (or rejects them), handles missing months (treat as 0, exclude those prescribers, or reject), rounds fractional counts, reads `;`/tab-delimited and Latin-1 files, keeps long IDs as text, and reports bad values with **file row numbers**. Limits come from `config.json` (25 MB, 5,000 prescribers, 60 months).

You also name things your way (the volume, the prescriber, each channel, region, tier, territory) and may give the value of one unit and the cost per channel unit; ROI, optimizer and incentive economics use your numbers. Headings, KPIs, chart titles, table columns, insights, Excel sheets and the PowerPoint all use these names, and filters or channels your file does not have disappear.

A realistic test file is in `samples/lipidex_prescriber_extract.csv` (different column names, text dates, four segments, territories, blanks, duplicates and gaps). `python scripts/load_sample_upload.py` loads it through the same code path as the wizard; `scripts/make_sample_upload.py` regenerates it. A blank template downloads from the upload card.

## BI tools: Tableau, Power BI, Sisense
They connect straight to PostgreSQL (see **BI connections** in the app for live connection details and per-tool steps).

* **Star schema (views, always current):** `bi_fact_hcp_month`, `bi_dim_hcp`, `bi_dim_territory`, `bi_dim_month` (real DATE keys).
* **Analysis tables (published after every upload and on demand):** `bi_model_terms`, `bi_channel_roi`, `bi_call_plan`, `bi_targeting_deciles`, `bi_hcp_segment`, `bi_ic_territory_quarter`, `bi_ic_payout_curve`, plus `bi_dataset_labels` (your wording) and `bi_refresh_log`.
* **No database access?** Download the CSV pack (every `bi_*` object as CSV) and load the files.
* **Read-only login:** `psql -U postgres -d promo -v bi_password="'secret'" -v schema=public -f scripts/create_bi_user.sql`.

### Ready-made Tableau workbook and Power BI project
Both are generated from whatever data set is loaded (sample or your upload), so titles, field names and charts follow your own labels, and a chart is only built when its columns exist and carry more than one value.

| | Tableau | Power BI |
|---|---|---|
| Get it | **BI connections** page > Download Tableau workbook, or `python scripts/build_tableau.py` | **BI connections** page > Download Power BI project, or `python scripts/build_powerbi.py` |
| Open with | Tableau Public (free) or Desktop: open `RxLift.twbx` | Power BI Desktop (free): open `RxLift.pbip`, then Home > Refresh |
| Contents | 9 worksheets, 2 dashboards (Performance; Where to focus and incentive plan), `.hyper` extracts | 11 tables, 5 relationships, measures, 3 pages (Performance, Where to focus, Incentive plan) |
| Data | Packaged as extracts (Tableau Public only accepts extracts), no login | CSV files read through the `DataFolder` parameter (Transform data > Edit parameters if you move the folder) |

Needs `pip install -r requirements-bi.txt` (Tableau's Hyper API) for the Tableau export; the Power BI export needs nothing extra. Both were opened and checked in the real applications (screenshots in `docs/bi/`), and the generated files are validated in the test suite (every report field exists in the model, extract row counts match the database). Generated files carry machine-specific paths, so `bi/` is git-ignored: generate them on the machine that will open them. Sisense is covered by the connection steps and CSV pack only; no Sisense dashboard is built.

![Tableau dashboard](docs/bi/tableau.png)
![Power BI report](docs/bi/powerbi.png)

The connections and the star-schema joins are verified by the test suite and through PostgreSQL. Tableau, Power BI and Sisense themselves are commercial tools and are not part of this repository.

## Pages
| Page | What it answers |
|---|---|
| Overview | KPIs, auto-written insights, trend, breakdown, top prescribers |
| Response model | Which channels move volume, by how much, at what ROI; carry-over search |
| Optimizer | Best allocation of the main channel for a budget (what-if slider) |
| Targeting | Is activity aligned with potential? Deciles, response-based segments, mis-aligned prescribers |
| Incentive comp | Territory quota attainment, payout curve and cost; what-if on quota growth, threshold, accelerator |
| Prescriber explorer | Server-side search, sort and paging over every prescriber |
| Data & reports | Current data set, upload wizard, load history, data dictionary, Excel/PowerPoint exports |
| BI connections | Connection details, published objects, refresh, CSV pack, tool steps |

![Incentive compensation](docs/incentive.png)

## How it works
* **Warehouse:** PostgreSQL with constraints, indexes and views (`app/sql/`). Loads are transactional.
* **Response model:** prescriber fixed-effects log-log regression with adstock carry-over (decay chosen by grid search), per-tier elasticities with 95% intervals. Within-prescriber R² is low on noisy counts; judge it by the coefficients and intervals.
* **Optimizer:** greedy marginal allocation of the budget (exact for concave curves).
* **Incentive engine:** quota = same quarter last year x (1 + growth); payout is linear to 100% at quota, then accelerates to a cap. All plan parameters are in `config.json` and overridable per request.
* **Stack:** FastAPI, SQLAlchemy/psycopg, pandas, NumPy, openpyxl, python-pptx; Vite, Chart.js and the Montserrat typeface (same as the IFMS platform, self-hosted) for the UI (plain modules, no framework).

## Tests
```powershell
$env:TEST_DATABASE_URL = "postgresql+psycopg://promo:promo@localhost:5432/promo"
.\.venv\Scripts\python -m pytest -q
```
Each run uses its own throw-away schema. Covered: data and SQL constraints, model recovery of the true effects, optimizer, incentive reconciliation against SQL, targeting, upload mapping/validation/cleaning (CSV and Excel), per-data-set labels, BI views and tables, CORS, frontend serving and the API.

## API
`/api/health`, `/api/meta`, `/api/kpis`, `/api/trend`, `/api/breakdown/{dimension}`, `/api/top-hcps`, `/api/hcps`, `/api/model`, `/api/optimize`, `/api/targeting`, `/api/incentive`, `/api/insights`, `/api/data-info`, `/api/data-dictionary`, `/api/upload/{spec,template,inspect,import}`, `/api/data/reset-sample`, `/api/bi/{info,refresh}`, `/api/export/{xlsx,pptx,bi,tableau,powerbi}`. Filters: `region`, `specialty`, `tier`, `start`, `end` (YYYY-MM).
