-- migrate:up

ALTER TABLE raw.xbrl_facts ADD COLUMN decimals text;   -- XBRL precision: an integer as text, or 'INF'

-- One row per concept a filing mentions (in facts, linkbases, or label linkbase).
CREATE TABLE raw.xbrl_concepts (
    filing_id   bigint  NOT NULL REFERENCES raw.filing,
    concept     text    NOT NULL,              -- 'us-gaap:Revenues'
    period_type text,                          -- 'instant' | 'duration'
    balance     text,                          -- 'debit' | 'credit'; NULL for us-gaap/dei (their schema is not in the filing)
    data_type   text,                          -- NULL for us-gaap/dei, same reason
    is_abstract boolean NOT NULL DEFAULT false,-- heading only, never carries a value
    labels      jsonb   NOT NULL DEFAULT '{}', -- {label_role_uri: text}
    PRIMARY KEY (filing_id, concept)
);

-- One row per presentation or calculation network (role) a filing declares.
CREATE TABLE raw.xbrl_roles (
    filing_id  bigint NOT NULL REFERENCES raw.filing,
    role_uri   text   NOT NULL,
    definition text,                           -- e.g. '0000002 - Statement - CONSOLIDATED BALANCE SHEETS'
    PRIMARY KEY (filing_id, role_uri)
);

-- Presentation linkbase: one row per parent->child arc. 'position' is the child's
-- rank among its parent's children; the same child may appear twice under one parent.
CREATE TABLE raw.xbrl_presentation_arcs (
    filing_id            bigint NOT NULL,
    role_uri             text   NOT NULL,
    parent_concept       text   NOT NULL,
    child_concept        text   NOT NULL,
    position             int    NOT NULL,
    preferred_label_role text,                 -- which label to display, e.g. '.../totalLabel'
    PRIMARY KEY (filing_id, role_uri, parent_concept, position),
    FOREIGN KEY (filing_id, role_uri) REFERENCES raw.xbrl_roles
);
CREATE INDEX xbrl_pres_child_idx ON raw.xbrl_presentation_arcs (filing_id, role_uri, child_concept);

-- Calculation linkbase: parent = sum(weight * child).
CREATE TABLE raw.xbrl_calculation_arcs (
    filing_id      bigint  NOT NULL,
    role_uri       text    NOT NULL,
    parent_concept text    NOT NULL,
    child_concept  text    NOT NULL,
    weight         numeric NOT NULL,           -- +1 or -1
    arc_order      numeric,
    PRIMARY KEY (filing_id, role_uri, parent_concept, child_concept),
    FOREIGN KEY (filing_id, role_uri) REFERENCES raw.xbrl_roles
);

-- Replaces raw.statement_line (never loaded)
DROP TABLE raw.statement_line;

-- migrate:down
CREATE TABLE raw.statement_line (
    filing_id      bigint  NOT NULL REFERENCES raw.filing,
    statement_type text    NOT NULL,
    line_order     integer NOT NULL,
    concept        text    NOT NULL,
    label          text,
    level          smallint,
    is_abstract    boolean NOT NULL DEFAULT false,
    parent_concept text,
    preferred_sign smallint,
    PRIMARY KEY (filing_id, statement_type, line_order)
);
DROP TABLE raw.xbrl_calculation_arcs;
DROP TABLE raw.xbrl_presentation_arcs;
DROP TABLE raw.xbrl_roles;
DROP TABLE raw.xbrl_concepts;
ALTER TABLE raw.xbrl_facts DROP COLUMN decimals;