-- migrate:up
CREATE SCHEMA IF NOT EXISTS derived;

-- Hand-curated reference data (not rebuildable from raw, so it lives in ref).
-- Which root heading concept marks which primary statement.
CREATE TABLE ref.statement_root (
    root_concept   text PRIMARY KEY,
    statement_type text NOT NULL
);
INSERT INTO ref.statement_root VALUES
    ('us-gaap:StatementOfFinancialPositionAbstract',              'BalanceSheet'),
    ('us-gaap:IncomeStatementAbstract',                           'IncomeStatement'),
    ('us-gaap:StatementOfCashFlowsAbstract',                      'CashFlowStatement'),
    ('us-gaap:StatementOfStockholdersEquityAbstract',             'StatementOfEquity'),
    ('us-gaap:StatementOfIncomeAndComprehensiveIncomeAbstract',   'ComprehensiveIncome');

-- Standard item -> candidate concepts, best first (lowest priority number wins).
CREATE TABLE ref.concept_map (
    standard_item  text NOT NULL,
    statement_type text NOT NULL,
    concept        text NOT NULL,
    priority       int  NOT NULL,
    PRIMARY KEY (standard_item, concept)
);
INSERT INTO ref.concept_map (standard_item, statement_type, concept, priority) VALUES
    ('revenue',              'IncomeStatement',   'us-gaap:Revenues', 1),
    ('revenue',              'IncomeStatement',   'us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax', 2),
    ('revenue',              'IncomeStatement',   'us-gaap:SalesRevenueNet', 3),
    ('operating_income',     'IncomeStatement',   'us-gaap:OperatingIncomeLoss', 1),
    ('net_income',           'IncomeStatement',   'us-gaap:NetIncomeLoss', 1),
    ('net_income',           'IncomeStatement',   'us-gaap:ProfitLoss', 2),
    ('eps_diluted',          'IncomeStatement',   'us-gaap:EarningsPerShareDiluted', 1),
    ('cash',                 'BalanceSheet',      'us-gaap:CashAndCashEquivalentsAtCarryingValue', 1),
    ('total_assets',         'BalanceSheet',      'us-gaap:Assets', 1),
    ('total_liabilities',    'BalanceSheet',      'us-gaap:Liabilities', 1),
    ('stockholders_equity',  'BalanceSheet',      'us-gaap:StockholdersEquity', 1),
    ('stockholders_equity',  'BalanceSheet',      'us-gaap:StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest', 2),
    ('liabilities_and_equity','BalanceSheet',     'us-gaap:LiabilitiesAndStockholdersEquity', 1),
    ('operating_cash_flow',  'CashFlowStatement', 'us-gaap:NetCashProvidedByUsedInOperatingActivities', 1);

-- derived.* tables are rebuilt in full by db/transforms/*.sql (see src/etl/derive.py).

-- Tier 1a: every (filing, role, root heading), classified when the root is known.
CREATE TABLE derived.statement (
    filing_id        bigint  NOT NULL REFERENCES raw.filing,
    role_uri         text    NOT NULL,
    root_concept     text    NOT NULL,
    definition       text,
    statement_type   text,                     -- NULL = not a primary statement (notes, details, unmapped roots)
    is_parenthetical boolean NOT NULL,
    PRIMARY KEY (filing_id, role_uri, root_concept)
);

-- Tier 1b: each statement flattened into display order.
CREATE TABLE derived.statement_line (
    filing_id            bigint   NOT NULL,
    role_uri             text     NOT NULL,
    root_concept         text     NOT NULL,
    line_no              int      NOT NULL,
    depth                smallint NOT NULL,
    concept              text     NOT NULL,
    parent_concept       text,
    label                text     NOT NULL,
    preferred_label_role text,
    period_role          text,                 -- 'start' | 'end' for cash roll-forward lines, else NULL
    display_sign         smallint NOT NULL,    -- -1 when the filer asks for the value to be shown negated
    is_abstract          boolean  NOT NULL,
    PRIMARY KEY (filing_id, role_uri, root_concept, line_no),
    FOREIGN KEY (filing_id, role_uri, root_concept) REFERENCES derived.statement
);

-- Tier 1c: statement lines joined to undimensioned numeric facts.
CREATE TABLE derived.statement_value (
    filing_id        bigint  NOT NULL,
    role_uri         text    NOT NULL,
    root_concept     text    NOT NULL,
    line_no          int     NOT NULL,
    statement_type   text    NOT NULL,
    is_parenthetical boolean NOT NULL,
    concept          text    NOT NULL,
    period_start     date,
    period_end       date    NOT NULL,
    duration_months  int,                      -- NULL for instants
    is_current       boolean NOT NULL,         -- period_end = the filing's own period end
    unit             text,
    value_reported   numeric NOT NULL,         -- as filed
    value_display    numeric NOT NULL,         -- value_reported * display_sign
    UNIQUE NULLS NOT DISTINCT (filing_id, role_uri, root_concept, line_no, period_start, period_end, unit),
    FOREIGN KEY (filing_id, role_uri, root_concept, line_no)
        REFERENCES derived.statement_line
);

-- Tier 2: standardized, comparable items for the current period of each filing.
CREATE TABLE derived.fundamentals (
    filing_id       bigint  NOT NULL REFERENCES raw.filing,
    standard_item   text    NOT NULL,
    period_end      date    NOT NULL,
    duration_months int,                       -- NULL for instants
    unit            text,
    value           numeric NOT NULL,
    source_concept  text    NOT NULL,          -- provenance: which concept supplied the value
    source_priority int     NOT NULL,
    UNIQUE NULLS NOT DISTINCT (filing_id, standard_item, period_end, duration_months, unit)
);

-- migrate:down
DROP TABLE derived.fundamentals;
DROP TABLE derived.statement_value;
DROP TABLE derived.statement_line;
DROP TABLE derived.statement;
DROP TABLE ref.concept_map;
DROP TABLE ref.statement_root;
DROP SCHEMA derived;