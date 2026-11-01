-- migrate:up
ALTER TABLE ref.company
	ADD COLUMN industry text NOT NULL,
	ADD COLUMN fiscal_year_end text NOT NULL;

-- migrate:down
ALTER TABLE ref.company
	DROP COLUMN fiscal_year_end,
	DROP COLUMN industry;

