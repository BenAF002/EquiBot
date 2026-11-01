
from datetime import date
from edgar.entity import EntityFiling
from edgar.entity.core import Company
from etl.db import connect
from config import PARSER_VERSION
from classifiers import score_sections

def upsert_company(company: Company, replace_entry: bool = False) -> int:
    """Update ref.company table with the given company information.
    
    Idempotent operation unless `replace_entry` is set to True.
    Returns:
        int: The `company_id` of the inserted or updated company.
    """
    ticker = company.tickers[0]
    cik = company.cik
    name = company.name
    industry = company.industry
    fiscal_year_end = company.fiscal_year_end

    with connect() as conn:
        cur = conn.cursor()
        if replace_entry:
            cur.execute(
                """
                REPLACE INTO ref.company (ticker, cik, name, industry, fiscal_year_end)
                VALUES (%s, %s, %s, %s, %s)
                RETURNING company_id
                """,
                (ticker, cik, name, industry, fiscal_year_end),
            )
        else:
            cur.execute(
                # uses `DO UPDATE` on conflict so that we can return `company_id`
                # `SET` variables are mostly arbitrary, but all can change so can be worth updating
                """
                INSERT INTO ref.company (ticker, cik, name, industry, fiscal_year_end)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (ticker) DO UPDATE SET 
                    name = EXCLUDED.name
                    , industry = EXCLUDED.industry
                    , fiscal_year_end = EXCLUDED.fiscal_year_end
                RETURNING company_id
                """,
                (ticker, cik, name, industry, fiscal_year_end),
            )
        
        company_id = cur.fetchone()["company_id"]
    
    return company_id


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
    fye_year = period_end.year
    if (period_end.month, period_end.day) > (fye_month, fye_day):
        fye_year += 1

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


def _upsert_filing_record(company: Company, filing: EntityFiling, company_id: int | str) -> int:
    """Upsert filing into `raw.filing` table

    Returns:
        int: The `filing_id` of the inserted filing.
    """
    fiscal_year = company.fiscal_year_end

    accession_no = filing.accession_number
    form_type = filing.form
    period_end = filing.period_of_report
    fiscal_period = _resolve_fiscal_period(company, filing)
    published_at = filing.filing_date
    source_url = filing.filing_url
    parser_version = PARSER_VERSION

    # insert the filing into `raw.filing`
    with connect() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO raw.filing (
                company_id , accession_no , form_type , period_end
                , fiscal_year , fiscal_period , published_at , source_url
                , parser_version
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (accession_no) DO UPDATE SET period_end = EXCLUDED.period_end
            RETURNING filing_id
            """,
            (
                company_id, accession_no, form_type, period_end,
                fiscal_year, fiscal_period, published_at, source_url,
                parser_version,
            ),
        )
        return cur.fetchone()['filing_id']


def _upsert_filing_sections(filing, filing_id: int | str) -> int:
    """Upsert section into raw.filing_section"""

    # get classification results for all sections
    laya_res = score_sections(filing, max_len=100)

    # upsert each section into `raw.filing_items`
    with connect() as conn:
        cur = conn.cursor()
        for section in filing.obj().sections:
            section_pred = laya_res.get(section, {}).get("pred")  # item label is predicted by classifier
            cur.execute(
                """
                INSERT INTO raw.filing_items (
                    filing_id, item_label, section_key, item_content, parser_version
                )
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (filing_id, section_key, item_label) DO NOTHING
                """,
                (filing_id, section_pred, section, filing.obj().sections.get(section).text(), PARSER_VERSION),
            )



# upsert everything for one report filing
def upsert_filing(company: Company, filing: EntityFiling, company_id: int | str | None = None) -> int:
    """Upsert a filing and its sections into the database at raw.filing and raw.filing_items."""
    
    # attempt to get company_id from ref.company if not provided
    if company_id is None:
        ticker = company.tickers[0]
        with connect() as conn:
            cur = conn.cursor()
            cur.execute(f"SELECT company_id FROM ref.company WHERE ticker = '{ticker}'")
            row = cur.fetchone()
        if row is None:
            raise ValueError(f"No company found in ref.company for ticker {ticker!r}")
        company_id = row["company_id"]

    filing_id = _upsert_filing_record(company, filing, company_id)
    _upsert_filing_sections(filing, filing_id)
    return filing_id
