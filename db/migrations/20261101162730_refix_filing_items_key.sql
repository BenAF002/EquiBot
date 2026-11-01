-- migrate:up
ALTER TABLE raw.filing_items DROP CONSTRAINT filing_items_pkey;
ALTER TABLE raw.filing_items ADD PRIMARY KEY (filing_id, section_key);
COMMENT ON COLUMN raw.filing_items.section_key IS 'edgartools section name; identifies the item within a filing';
COMMENT ON COLUMN raw.filing_items.item_label IS 'classifier-assigned category; non-deterministic, rewritten on rescore';

-- migrate:down
COMMENT ON COLUMN raw.filing_items.item_label IS NULL;
COMMENT ON COLUMN raw.filing_items.section_key IS NULL;
ALTER TABLE raw.filing_items DROP CONSTRAINT filing_items_pkey;
ALTER TABLE raw.filing_items ADD PRIMARY KEY (filing_id, section_key, item_label);