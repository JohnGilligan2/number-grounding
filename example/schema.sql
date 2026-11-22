-- A small, made-up reporting schema for a multi-office dental practice. The tool results in
-- tool_results.json are what MCP tools over tables like these would return. Every office,
-- provider and dollar figure in this folder is invented.
--
-- Reporting tables hold totals only, never patient rows: a cell with fewer than 11 patients is
-- hidden at load time, and the tools say so instead of returning zero.

CREATE TABLE office (
    office_id   INTEGER PRIMARY KEY,
    name        TEXT NOT NULL,          -- 'Office A'
    connected   INTEGER NOT NULL        -- 0 = no nightly feed yet; tools report "unknown"
);

CREATE TABLE provider (
    provider_id INTEGER PRIMARY KEY,
    office_id   INTEGER NOT NULL REFERENCES office(office_id),
    label       TEXT NOT NULL           -- 'Provider A'
);

-- One row per provider per month.
CREATE TABLE production_month (
    provider_id      INTEGER NOT NULL REFERENCES provider(provider_id),
    month            TEXT NOT NULL,     -- '2026-02'
    gross_production REAL NOT NULL,
    adjustments      REAL NOT NULL,     -- negative
    net_production   REAL NOT NULL,     -- gross + adjustments
    PRIMARY KEY (provider_id, month)
);

-- One row per office per week; the 8-week average is computed by the tool.
CREATE TABLE office_week (
    office_id       INTEGER NOT NULL REFERENCES office(office_id),
    week_start      TEXT NOT NULL,      -- Monday, '2026-03-09'
    collections     REAL,               -- NULL when hidden
    net_production  REAL,
    booked_minutes  INTEGER,
    open_minutes    INTEGER,            -- fill_rate = booked / open
    PRIMARY KEY (office_id, week_start)
);

-- Patient balances by age bucket, summed per office.
CREATE TABLE ar_aging (
    office_id       INTEGER NOT NULL REFERENCES office(office_id),
    as_of           TEXT NOT NULL,
    bal_0_30        REAL, bal_31_60 REAL, bal_61_90 REAL, bal_over_90 REAL,
    credit_balances REAL,               -- negative: patients owed money back
    PRIMARY KEY (office_id, as_of)
);
