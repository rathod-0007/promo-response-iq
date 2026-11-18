PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS hcp (
    hcp_id      INTEGER PRIMARY KEY,
    name        TEXT    NOT NULL,
    specialty   TEXT    NOT NULL,
    region      TEXT    NOT NULL,
    tier        TEXT    NOT NULL CHECK (tier IN ('A','B','C'))
);

CREATE TABLE IF NOT EXISTS activity (
    hcp_id   INTEGER NOT NULL REFERENCES hcp(hcp_id),
    month    TEXT    NOT NULL CHECK (month GLOB '[0-9][0-9][0-9][0-9]-[0-1][0-9]'),
    calls    INTEGER NOT NULL CHECK (calls   >= 0),
    samples  INTEGER NOT NULL CHECK (samples >= 0),
    emails   INTEGER NOT NULL CHECK (emails  >= 0),
    PRIMARY KEY (hcp_id, month)
);

CREATE TABLE IF NOT EXISTS rx (
    hcp_id  INTEGER NOT NULL REFERENCES hcp(hcp_id),
    month   TEXT    NOT NULL CHECK (month GLOB '[0-9][0-9][0-9][0-9]-[0-1][0-9]'),
    trx     INTEGER NOT NULL CHECK (trx >= 0),
    PRIMARY KEY (hcp_id, month)
);

CREATE INDEX IF NOT EXISTS ix_activity_month ON activity(month);
CREATE INDEX IF NOT EXISTS ix_rx_month ON rx(month);
CREATE INDEX IF NOT EXISTS ix_hcp_region ON hcp(region, specialty, tier);
