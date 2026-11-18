-- Analysis grain: one row per HCP per month. BI tools (Tableau / Power BI) can connect here.
DROP VIEW IF EXISTS v_hcp_month;
CREATE VIEW v_hcp_month AS
SELECT a.hcp_id, a.month, h.specialty, h.region, h.tier,
       a.calls, a.samples, a.emails, r.trx
FROM activity a
JOIN hcp h ON h.hcp_id = a.hcp_id
JOIN rx  r ON r.hcp_id = a.hcp_id AND r.month = a.month;

DROP VIEW IF EXISTS v_monthly_summary;
CREATE VIEW v_monthly_summary AS
SELECT month,
       SUM(trx)     AS trx,
       SUM(calls)   AS calls,
       SUM(samples) AS samples,
       SUM(emails)  AS emails,
       COUNT(DISTINCT hcp_id) AS hcps
FROM v_hcp_month
GROUP BY month;

DROP VIEW IF EXISTS v_region_summary;
CREATE VIEW v_region_summary AS
SELECT region,
       SUM(trx)   AS trx,
       SUM(calls) AS calls,
       COUNT(DISTINCT hcp_id) AS hcps,
       ROUND(1.0 * SUM(trx) / NULLIF(SUM(calls), 0), 3) AS trx_per_call
FROM v_hcp_month
GROUP BY region;
