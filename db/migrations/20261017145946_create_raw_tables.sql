-- migrate:up
CREATE TABLE raw.filing (
    filing_id      bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,  -- generated UID, ALWAYS prevents manual ID assignment
    company_id     bigint NOT NULL REFERENCES ref.company,
    accession_no   text   NOT NULL UNIQUE,   -- SEC's own id; the natural key
    form_type      text   NOT NULL,          -- '10-K', '10-Q', '8-K', '10-K/A'
    period_end     date,
    fiscal_year    smallint,
    fiscal_period  text,                     -- 'FY', 'Q1', 'Q2', 'Q3'
    published_at   timestamptz NOT NULL,     -- SEC acceptance time (when knowable)
    ingested_at    timestamptz NOT NULL DEFAULT now(),
    source_url     text   NOT NULL,
    parser_version text   NOT NULL,
    meta           jsonb  NOT NULL DEFAULT '{}'
);
CREATE INDEX filing_company_pub_idx ON raw.filing (company_id, published_at DESC);


CREATE TABLE raw.filing_section (
    filing_id      bigint NOT NULL REFERENCES raw.filing,
    section_key    text   NOT NULL,          -- normalized: 'business', 'risk_factors', 'mdna'
    item_label     text,                     -- as filed: 'Item 1A', 'Item 7'
    body_text      text   NOT NULL,
    parser_version text   NOT NULL,
    search_vec     tsvector
        GENERATED ALWAYS AS (to_tsvector('english', body_text)) STORED,
    PRIMARY KEY (filing_id, section_key)
);
CREATE INDEX filing_section_search_idx ON raw.filing_section USING gin (search_vec);


CREATE TABLE raw.xbrl_fact (
    fact_id      bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    filing_id    bigint NOT NULL REFERENCES raw.filing,
    concept      text   NOT NULL,            -- 'us-gaap:Revenues' or a company extension
    period_start date,                       -- NULL for point-in-time (balance sheet) facts
    period_end   date   NOT NULL,            -- the instant, or the end of the duration
    dimensions   jsonb  NOT NULL DEFAULT '{}',  -- {"<axis>": "<member>"}; {} = consolidated total
    unit         text,                       -- 'USD', 'shares', 'USD/shares'
    value_num    numeric,
    value_text   text,                       -- string facts and note text blocks
    UNIQUE NULLS NOT DISTINCT
        (filing_id, concept, period_start, period_end, dimensions, unit)
);
CREATE INDEX xbrl_fact_concept_period_idx ON raw.xbrl_fact (concept, period_end);


CREATE TABLE raw.statement_line (
    filing_id      bigint  NOT NULL REFERENCES raw.filing,
    statement_type text    NOT NULL,         -- 'IncomeStatement', 'BalanceSheet', ...
    line_order     integer NOT NULL,
    concept        text    NOT NULL,
    label          text,
    level          smallint,
    is_abstract    boolean NOT NULL DEFAULT false,
    parent_concept text,
    preferred_sign smallint,
    PRIMARY KEY (filing_id, statement_type, line_order)
);


-- migrate:down
DROP TABLE raw.statement_line;
DROP TABLE raw.xbrl_fact;
DROP TABLE raw.filing_section;
DROP TABLE raw.filing;