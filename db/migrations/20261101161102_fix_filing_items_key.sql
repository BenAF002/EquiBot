-- migrate:up
ALTER TABLE raw.filing_items DROP CONSTRAINT filing_items_pkey;
ALTER TABLE raw.filing_items ADD PRIMARY KEY (filing_id, item_label);
ALTER TABLE raw.filing_items ALTER COLUMN section_key DROP NOT NULL;

-- migrate:down
ALTER TABLE raw.filing_items DROP CONSTRAINT filing_items_pkey;
ALTER TABLE raw.filing_items ADD PRIMARY KEY (filing_id, section_key, item_label);