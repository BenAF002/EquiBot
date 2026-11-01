-- migrate:up
ALTER TABLE raw.filing_items DROP COLUMN item_label;

-- migrate:down
ALTER TABLE raw.filing_items ADD COLUMN item_label text;
COMMENT ON COLUMN raw.filing_items.item_label IS 'classifier-assigned category; non-deterministic, rewritten on rescore';
