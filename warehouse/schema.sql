-- Raw tables for the made-up FDE warehouse. Loaded by warehouse/build.py.

CREATE OR REPLACE TABLE roster (
    fde_id        VARCHAR PRIMARY KEY,
    role          VARCHAR NOT NULL,     -- FDE | Senior FDE | Eng Manager
    region        VARCHAR NOT NULL,     -- AMER | EMEA | APAC
    hire_date     DATE    NOT NULL,
    term_date     DATE                  -- NULL = still employed
);

CREATE OR REPLACE TABLE requisitions (
    req_id        VARCHAR PRIMARY KEY,
    role          VARCHAR NOT NULL,
    region        VARCHAR NOT NULL,
    opened_date   DATE    NOT NULL,
    filled_date   DATE,                 -- NULL = still open
    fde_id        VARCHAR
);

CREATE OR REPLACE TABLE accounts (
    account_id    VARCHAR PRIMARY KEY,
    segment       VARCHAR NOT NULL,     -- Commercial | Research | Mission
    region        VARCHAR NOT NULL
);

CREATE OR REPLACE TABLE partners (
    partner_id    VARCHAR PRIMARY KEY,
    partner_name  VARCHAR NOT NULL
);

CREATE OR REPLACE TABLE fde_requests (
    request_id     VARCHAR PRIMARY KEY,
    account_id     VARCHAR NOT NULL,
    segment        VARCHAR NOT NULL,
    region         VARCHAR NOT NULL,
    type           VARCHAR NOT NULL,    -- Greenfield | Pattern-based | Expansion
    requested_date DATE    NOT NULL,
    decision_date  DATE,                -- NULL while still in scoping
    decision       VARCHAR NOT NULL,    -- accepted | declined_fit | declined_capacity | pending
    engagement_id  VARCHAR              -- set when accepted
);

CREATE OR REPLACE TABLE engagements (
    engagement_id  VARCHAR PRIMARY KEY,
    request_id     VARCHAR NOT NULL,
    account_id     VARCHAR NOT NULL,
    segment        VARCHAR NOT NULL,
    region         VARCHAR NOT NULL,
    type           VARCHAR NOT NULL,
    partner_led    BOOLEAN NOT NULL,
    partner_id     VARCHAR,
    fdes_planned   DOUBLE  NOT NULL,    -- FDE allocation (FTE) planned at kickoff
    signed_date    DATE    NOT NULL,
    kickoff_date   DATE,                -- NULL = still waiting for staffing
    prod_date      DATE,                -- NULL = not (yet) in production
    closed_date    DATE,                -- NULL = still active
    had_blocker    BOOLEAN,
    partner_hours  DOUBLE,              -- hours invoiced by the partner (partner-led only)
    status         VARCHAR NOT NULL     -- queued | in_build | live_handoff | closed | cancelled
);

CREATE OR REPLACE TABLE staffing (
    engagement_id  VARCHAR NOT NULL,
    fde_id         VARCHAR NOT NULL,
    allocation     DOUBLE  NOT NULL,    -- share of the FDE's deployable time
    start_date     DATE    NOT NULL,
    end_date       DATE                 -- NULL = still assigned
);

CREATE OR REPLACE TABLE time_entries (
    fde_id         VARCHAR NOT NULL,
    week_start     DATE    NOT NULL,
    category       VARCHAR NOT NULL,    -- deploy | presales | internal | harvest | pto | bench
    engagement_id  VARCHAR,             -- set for deploy hours
    hours          DOUBLE  NOT NULL
);

CREATE OR REPLACE TABLE assets (
    asset_id             VARCHAR PRIMARY KEY,
    asset_type           VARCHAR NOT NULL,
    source_engagement_id VARCHAR,       -- NULL for the starting library
    created_date         DATE    NOT NULL,
    deprecated_date      DATE
);

CREATE OR REPLACE TABLE asset_usage (
    engagement_id      VARCHAR NOT NULL,
    asset_id           VARCHAR NOT NULL,
    effort_hours_saved DOUBLE  NOT NULL
);

CREATE OR REPLACE TABLE consumption (
    account_id   VARCHAR NOT NULL,
    month        DATE    NOT NULL,      -- first of month
    spend_usd    DOUBLE  NOT NULL
);
