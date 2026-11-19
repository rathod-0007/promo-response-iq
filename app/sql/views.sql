-- Analysis grain: one row per HCP per month. BI tools (Tableau / Power BI) can connect here.
DROP VIEW IF EXISTS bi_flat_hcp_month;
DROP VIEW IF EXISTS bi_fact_hcp_month;
DROP VIEW IF EXISTS bi_dim_month;
DROP VIEW IF EXISTS bi_dim_territory;
DROP VIEW IF EXISTS bi_dim_hcp;
DROP VIEW IF EXISTS v_territory_month;
DROP VIEW IF EXISTS v_region_summary;
DROP VIEW IF EXISTS v_monthly_summary;
DROP VIEW IF EXISTS v_hcp_month;

CREATE VIEW v_hcp_month AS
SELECT a.hcp_id, a.month::text AS month, h.specialty, h.region, h.tier,
       a.calls, a.samples, a.emails, r.trx, h.territory_id
FROM activity a
JOIN hcp h ON h.hcp_id = a.hcp_id
JOIN rx  r ON r.hcp_id = a.hcp_id AND r.month = a.month;

CREATE VIEW v_monthly_summary AS
SELECT month,
       SUM(trx)     AS trx,
       SUM(calls)   AS calls,
       SUM(samples) AS samples,
       SUM(emails)  AS emails,
       COUNT(DISTINCT hcp_id) AS hcps
FROM v_hcp_month
GROUP BY month;

CREATE VIEW v_region_summary AS
SELECT region,
       SUM(trx)   AS trx,
       SUM(calls) AS calls,
       COUNT(DISTINCT hcp_id) AS hcps,
       ROUND((1.0 * SUM(trx) / NULLIF(SUM(calls), 0))::numeric, 3)::float8 AS trx_per_call
FROM v_hcp_month
GROUP BY region;

-- Territory-month grain used by incentive-compensation analysis.
CREATE VIEW v_territory_month AS
SELECT t.territory_id, t.name AS territory, t.rep_name, t.region, v.month,
       SUM(v.trx) AS trx, SUM(v.calls) AS calls, COUNT(DISTINCT v.hcp_id) AS hcps
FROM v_hcp_month v
JOIN territory t ON t.territory_id = v.territory_id
GROUP BY t.territory_id, t.name, t.rep_name, t.region, v.month;

-- ---------------------------------------------------------------------------------------------
-- BI star schema: stable names, real DATE keys. Connect Tableau / Power BI / Sisense to these.
-- ---------------------------------------------------------------------------------------------
CREATE VIEW bi_dim_hcp AS
SELECT h.hcp_id, COALESCE(h.external_id, h.hcp_id::text) AS hcp_external_id, h.name AS hcp_name,
       h.specialty, h.region, h.tier, h.territory_id
FROM hcp h;

CREATE VIEW bi_dim_territory AS
SELECT territory_id, name AS territory_name, region, rep_name FROM territory;

CREATE VIEW bi_dim_month AS
SELECT DISTINCT to_date(a.month::text || '-01', 'YYYY-MM-DD') AS month_start, a.month::text AS month_key,
       EXTRACT(YEAR FROM to_date(a.month::text || '-01', 'YYYY-MM-DD'))::int AS year,
       EXTRACT(QUARTER FROM to_date(a.month::text || '-01', 'YYYY-MM-DD'))::int AS quarter,
       EXTRACT(YEAR FROM to_date(a.month::text || '-01', 'YYYY-MM-DD'))::int || '-Q' ||
       EXTRACT(QUARTER FROM to_date(a.month::text || '-01', 'YYYY-MM-DD'))::int AS quarter_label,
       to_char(to_date(a.month::text || '-01', 'YYYY-MM-DD'), 'Mon') AS month_name
FROM activity a;

CREATE VIEW bi_fact_hcp_month AS
SELECT a.hcp_id, to_date(a.month::text || '-01', 'YYYY-MM-DD') AS month_start, a.month::text AS month_key,
       r.trx, a.calls, a.samples, a.emails
FROM activity a JOIN rx r ON r.hcp_id = a.hcp_id AND r.month = a.month;

-- One wide table for tools that work best on a single table (Tableau Public, Excel pivots).
CREATE VIEW bi_flat_hcp_month AS
SELECT f.hcp_id, d.hcp_external_id, d.hcp_name, d.specialty, d.region, d.tier,
       d.territory_id, t.territory_name, t.rep_name,
       f.month_start, m.month_key, m.year, m.quarter, m.quarter_label, m.month_name,
       f.trx, f.calls, f.samples, f.emails
FROM bi_fact_hcp_month f
JOIN bi_dim_hcp d ON d.hcp_id = f.hcp_id
JOIN bi_dim_month m ON m.month_start = f.month_start
LEFT JOIN bi_dim_territory t ON t.territory_id = d.territory_id;

COMMENT ON VIEW bi_flat_hcp_month IS 'BI flat table: every prescriber-month with all prescriber, territory and calendar attributes';
COMMENT ON VIEW bi_dim_hcp IS 'BI dimension: one row per prescriber with segmentation attributes';
COMMENT ON VIEW bi_dim_territory IS 'BI dimension: one row per sales territory and its rep';
COMMENT ON VIEW bi_dim_month IS 'BI dimension: calendar months with year, quarter and month name';
COMMENT ON VIEW bi_fact_hcp_month IS 'BI fact: prescriptions and promotional activity per prescriber per month';
COMMENT ON VIEW v_hcp_month IS 'Analysis grain: one row per prescriber per month with all attributes';
COMMENT ON VIEW v_monthly_summary IS 'Totals per month';
COMMENT ON VIEW v_region_summary IS 'Totals and prescriptions per call by region';
COMMENT ON VIEW v_territory_month IS 'Prescriptions per territory per month (incentive compensation grain)';
