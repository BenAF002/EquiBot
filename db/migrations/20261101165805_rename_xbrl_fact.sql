-- migrate:up
ALTER TABLE raw.xbrl_fact RENAME TO xbrl_facts;
ALTER TABLE raw.xbrl_facts RENAME CONSTRAINT xbrl_fact_pkey TO xbrl_facts_pkey;
ALTER INDEX raw.xbrl_fact_concept_period_idx RENAME TO xbrl_facts_concept_period_idx;
ALTER SEQUENCE raw.xbrl_fact_fact_id_seq RENAME TO xbrl_facts_fact_id_seq;

-- migrate:down
ALTER SEQUENCE raw.xbrl_facts_fact_id_seq RENAME TO xbrl_fact_fact_id_seq;
ALTER INDEX raw.xbrl_facts_concept_period_idx RENAME TO xbrl_fact_concept_period_idx;
ALTER TABLE raw.xbrl_facts RENAME CONSTRAINT xbrl_facts_pkey TO xbrl_fact_pkey;
ALTER TABLE raw.xbrl_facts RENAME TO xbrl_fact;