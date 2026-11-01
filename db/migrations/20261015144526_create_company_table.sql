-- migrate:up
CREATE TABLE ref.company (
    company_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    ticker     text NOT NULL UNIQUE,
    cik        text UNIQUE,
    name       text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);

-- migrate:down
DROP TABLE IF EXISTS ref.company;

