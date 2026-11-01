-- migrate:up
-- replace raw.filing_section with raw.filing_items
DROP TABLE raw.filing_section;
CREATE TABLE raw.filing_items (
    filing_id      bigint NOT NULL REFERENCES raw.filing,
    item_label     text NOT NULL,
    section_key    text,  -- normalized: 'business', 'risk_factors', etc. Not available on all report types
    item_content   text,     -- the actual content of the item
    parser_version text,
    search_vec     tsvector
        GENERATED ALWAYS AS (to_tsvector('english', item_content)) STORED,
    PRIMARY KEY (filing_id, section_key, item_label)
);
CREATE INDEX filing_items_search_idx ON raw.filing_items USING gin (search_vec);

-- migrate:down
DROP TABLE raw.filing_items;
CREATE TABLE raw.filing_section ();

