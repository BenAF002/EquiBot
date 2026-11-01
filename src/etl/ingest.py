
import os
from decimal import Decimal

import pandas as pd
from datetime import date
from edgar.entity import EntityFiling
from edgar import Company, set_identity
from psycopg.types.json import Jsonb

from .db import connect
from .config import PARSER_VERSION

set_identity(os.environ["EDGAR_IDENTITY"])


## Helper functions for cleaning and normalizing data
def clean(v):
    """NaN/NaT -> None, numpy scalars -> Python scalars."""
    if v is None:
        return None
    try:
        if pd.isna(v):
            return None
    except (TypeError, ValueError):
        pass
    return v.item() if hasattr(v, "item") else v

def clean_date(v):
    v = clean(v)
    return None if v is None else pd.Timestamp(v).date()

def norm_concept(c):
    """'us-gaap_Revenues' -> 'us-gaap:Revenues' so facts and statement lines agree."""
    return c if ":" in c else c.replace("_", ":", 1)

def _resolve_fiscal_period(company: Company,filing: EntityFiling) -> str:
    """Resolve the fiscal period from form type, period end, and fiscal year end"""
    period_end = filing.period_of_report
    form_type = filing.form
    fiscal_year_end = company.fiscal_year_end

    if isinstance(period_end, str):
        period_end = date.fromisoformat(period_end)

    fye_month = int(fiscal_year_end[:2])
    fye_day = int(fiscal_year_end[2:])

    # Infer the fiscal year end date that follows (or equals) period_end
    fye_year = _resolve_fiscal_year(period_end, fiscal_year_end)

    # Months elapsed since the fiscal year start, based on the months between
    # period_end and fiscal year end (0 months remaining -> last quarter)
    months_to_fye = (fye_year - period_end.year) * 12 + (fye_month - period_end.month)
    months_since_start = 12 - months_to_fye  # 1..12

    quarter = (months_since_start - 1) // 3 + 1
    quarter_label = f"Q{quarter}"

    if form_type == "10-K":
        return "FY"
    elif form_type in ("10-Q", "8-K"):
        return quarter_label

def _resolve_fiscal_year(period_end: date | str, fiscal_year_end: str) -> int:
    """Infer the fiscal-year calendar year from a period end and an MMDD year end."""
    if isinstance(period_end, str):
        period_end = date.fromisoformat(period_end)

    fye_month = int(fiscal_year_end[:2])
    fye_day = int(fiscal_year_end[2:])
    fiscal_year = period_end.year
    if (period_end.month, period_end.day) > (fye_month, fye_day):
        fiscal_year += 1
    return fiscal_year


def upsert_company(company: Company, replace_entry: bool = False) -> int:
    """Update ref.company table with the given company information.
    
    Idempotent operation unless `replace_entry` is set to True.
    Returns:
        int: The `company_id` of the inserted or updated company.
    """
    with connect() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO ref.company (ticker, cik, name, industry, fiscal_year_end)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (cik) DO UPDATE SET
                ticker = EXCLUDED.ticker,
                name = EXCLUDED.name,
                industry = EXCLUDED.industry,
                fiscal_year_end = EXCLUDED.fiscal_year_end
            RETURNING company_id
            """,
            (company.tickers[0], company.cik, company.name, company.industry, company.fiscal_year_end),
        )
        company_id = cur.fetchone()["company_id"]
    
    return company_id


def _upsert_filing_record(conn, company: Company, filing: EntityFiling, company_id: int | str) -> int:
    """Upsert filing into `raw.filing` table

    Returns:
        int: The `filing_id` of the inserted filing.
    """
    # insert the filing into `raw.filing`
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO raw.filing (
            company_id 
            , accession_no 
            , form_type 
            , period_end
            , fiscal_year 
            , fiscal_period 
            , published_at 
            , source_url
            , parser_version
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (accession_no) DO UPDATE SET 
            period_end = EXCLUDED.period_end,
            fiscal_year = EXCLUDED.fiscal_year,
            fiscal_period = EXCLUDED.fiscal_period,
            published_at = EXCLUDED.published_at,
            source_url = EXCLUDED.source_url,
            parser_version = EXCLUDED.parser_version
        RETURNING filing_id
        """,
        (
            company_id, 
            filing.accession_number, 
            filing.form, 
            filing.period_of_report,
            _resolve_fiscal_year(filing.period_of_report, company.fiscal_year_end), 
            _resolve_fiscal_period(company, filing), 
            filing.filing_date, 
            filing.filing_url,
            PARSER_VERSION,
        ),
    )
    return cur.fetchone()['filing_id']


def _upsert_filing_sections(conn, filing, filing_id: int | str) -> int:
    """Upsert section into raw.filing_section"""

    sections = filing.obj().sections
    rows = []
    for section in sections:
        rows.append((filing_id, section, sections.get(section).text(), PARSER_VERSION))

    # upsert each section into `raw.filing_items`
    conn.cursor().executemany(
        """
        INSERT INTO raw.filing_items (filing_id, section_key, item_content, parser_version)
        VALUES (%s, %s, %s, %s)
        ON CONFLICT (filing_id, section_key) DO UPDATE SET 
            item_content = EXCLUDED.item_content,
            parser_version = EXCLUDED.parser_version
        """,
        rows
    )


def _upsert_xbrl_facts(conn, filing, filing_id: int | str) -> None:
    """Upsert XBRL facts into raw.xbrl_fact"""
    df = filing.xbrl().query().by_dimension(None).to_dataframe()
    # print("fact columns:", df.columns.tolist()) 

    rows, skipped = [], 0
    for r in df.to_dict("records"):
        end = clean_date(r.get("period_end") or r.get("period_instant"))
        if end is None:
            skipped += 1
            continue
        raw_value = clean(r.get("value"))
        num = pd.to_numeric(raw_value, errors="coerce")
        is_num = not pd.isna(num)
        rows.append((
            filing_id,
            norm_concept(r["concept"]),         # xbrl concept
            clean_date(r.get("period_start")),  # xbrl period start
            end,
            Jsonb({}),
            clean(r.get("unit")),                   # xbrl value unit
            Decimal(str(num)) if is_num else None,  # xbrl value numeric
            None if is_num else (str(raw_value) if raw_value is not None else None),  # xbrl value text
        ))
    conn.cursor().executemany(
        """INSERT INTO raw.xbrl_fact
            (filing_id, concept, period_start, period_end, dimensions,
            unit, value_num, value_text)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT DO NOTHING""",
        rows,
    )
    if skipped:
        print(f"  skipped {skipped} facts with no period end")
    return len(rows)


        


# upsert everything for one report filing
def upsert_filing(company: Company, filing: EntityFiling, company_id: int | str | None = None) -> int:
    """Upsert a filing and its sections into the database at raw.filing and raw.filing_items."""
    conn = connect()
    
    # using .transaction() ensures all or none of the section inserts are applied
    with conn.transaction():
        # attempt to get company_id from ref.company if not provided
        if company_id is None:
            ticker = company.tickers[0]
            cur = conn.cursor()
            cur.execute("SELECT company_id FROM ref.company WHERE ticker = %s", (ticker,))
            row = cur.fetchone()
            if row is None:
                raise ValueError(f"No company found in ref.company for ticker {ticker!r}")
            company_id = row["company_id"]

        filing_id = _upsert_filing_record(conn, company, filing, company_id)
        _upsert_filing_sections(conn, filing, filing_id)    # upsert section bodies for the filing
        _upsert_xbrl_facts(conn, filing, filing_id)         # upsert XBRL facts for the filing
        return filing_id
