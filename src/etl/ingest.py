
import os
from decimal import Decimal

import pandas as pd
from datetime import date
from edgar.entity import EntityFiling
from edgar import Company, set_identity
from psycopg.types.json import Jsonb

from .db import connect
from .config import PARSER_VERSION
from . import helpers as h
from . import xbrl_load as xl

set_identity(os.environ["EDGAR_IDENTITY"])


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
        xbrl_res = xl.load_xbrl(conn, filing.xbrl(), filing_id)         # upsert XBRL facts for the filing
        res = {"filing": {"filing_id": filing_id}, "xbrl": xbrl_res}
        return res
