-- Read-only login for Tableau / Power BI / Sisense. Run as a superuser or the database owner:
--   psql -U postgres -d promo -v bi_password="'choose-a-password'" -v schema=public -f scripts/create_bi_user.sql
-- BI tools then only SELECT; they cannot change the warehouse.
CREATE ROLE bi_reader LOGIN PASSWORD :bi_password;
SELECT format('GRANT CONNECT ON DATABASE %I TO bi_reader', current_database()) \gexec
GRANT USAGE ON SCHEMA :"schema" TO bi_reader;
GRANT SELECT ON ALL TABLES IN SCHEMA :"schema" TO bi_reader;
ALTER DEFAULT PRIVILEGES IN SCHEMA :"schema" GRANT SELECT ON TABLES TO bi_reader;
