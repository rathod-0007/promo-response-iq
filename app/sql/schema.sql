CREATE TABLE IF NOT EXISTS territory (
    territory_id  INTEGER PRIMARY KEY,
    name          TEXT NOT NULL,
    region        TEXT NOT NULL,
    rep_name      TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS hcp (
    hcp_id      INTEGER PRIMARY KEY,
    name        TEXT    NOT NULL,
    specialty   TEXT    NOT NULL,
    region      TEXT    NOT NULL,
    tier        TEXT    NOT NULL
);
ALTER TABLE hcp ADD COLUMN IF NOT EXISTS territory_id INTEGER REFERENCES territory(territory_id);
ALTER TABLE hcp ADD COLUMN IF NOT EXISTS external_id TEXT;
ALTER TABLE hcp DROP CONSTRAINT IF EXISTS hcp_tier_check;

CREATE TABLE IF NOT EXISTS activity (
    hcp_id   INTEGER NOT NULL REFERENCES hcp(hcp_id),
    month    CHAR(7) NOT NULL CHECK (month ~ '^[0-9]{4}-(0[1-9]|1[0-2])$'),
    calls    INTEGER NOT NULL CHECK (calls   >= 0),
    samples  INTEGER NOT NULL CHECK (samples >= 0),
    emails   INTEGER NOT NULL CHECK (emails  >= 0),
    PRIMARY KEY (hcp_id, month)
);

CREATE TABLE IF NOT EXISTS rx (
    hcp_id  INTEGER NOT NULL REFERENCES hcp(hcp_id),
    month   CHAR(7) NOT NULL CHECK (month ~ '^[0-9]{4}-(0[1-9]|1[0-2])$'),
    trx     INTEGER NOT NULL CHECK (trx >= 0),
    PRIMARY KEY (hcp_id, month)
);

CREATE TABLE IF NOT EXISTS data_load (
    load_id    BIGSERIAL PRIMARY KEY,
    loaded_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    source     TEXT NOT NULL
);
ALTER TABLE data_load ADD COLUMN IF NOT EXISTS profile JSONB;

CREATE INDEX IF NOT EXISTS ix_activity_month ON activity(month);
CREATE INDEX IF NOT EXISTS ix_rx_month ON rx(month);
CREATE INDEX IF NOT EXISTS ix_hcp_dims ON hcp(region, specialty, tier);
CREATE INDEX IF NOT EXISTS ix_hcp_territory ON hcp(territory_id);

-- Data dictionary (shown on the Data & reports page)
COMMENT ON TABLE  territory IS 'Sales territories; one field rep each';
COMMENT ON COLUMN territory.rep_name IS 'Field representative who owns the territory';
COMMENT ON TABLE  hcp IS 'Healthcare professionals (prescribers) with segmentation attributes';
COMMENT ON COLUMN hcp.tier IS 'Value tier / segment label (supplied, or derived from Rx volume)';
COMMENT ON COLUMN hcp.external_id IS 'Prescriber identifier as it appears in the source file (e.g. NPI)';
COMMENT ON COLUMN hcp.territory_id IS 'Territory that covers this HCP (nullable)';
COMMENT ON TABLE  activity IS 'Monthly promotional activity per HCP';
COMMENT ON COLUMN activity.calls IS 'Rep detailing calls in the month';
COMMENT ON COLUMN activity.samples IS 'Product samples dropped in the month';
COMMENT ON COLUMN activity.emails IS 'Approved e-mails sent in the month';
COMMENT ON TABLE  rx IS 'Monthly total prescriptions (TRx) written per HCP';
COMMENT ON COLUMN rx.trx IS 'Total prescriptions written in the month';
COMMENT ON TABLE  data_load IS 'Audit trail of warehouse loads';
COMMENT ON COLUMN data_load.profile IS 'Dataset profile: labels, channels, column mapping, economics, warnings';
