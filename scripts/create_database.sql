-- One-time local setup. Run as a PostgreSQL superuser, e.g.:
--   psql -U postgres -f scripts/create_database.sql
-- Creates the login and database that config.json points to by default (override with DATABASE_URL).
CREATE ROLE promo LOGIN PASSWORD 'promo';
CREATE DATABASE promo OWNER promo;
