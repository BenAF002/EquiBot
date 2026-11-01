import gzip
import hashlib
from pathlib import Path
from edgar import use_local_storage, download_filings
from edgar.settings import get_edgar_data_directory

CACHE = Path(".edgar_cache")
CACHE.mkdir(exist_ok=True)
use_local_storage(CACHE)



def ingest_one(conn, company_id, filing):
    local = Path(filing.get_local_path())  # print this once to confirm the location
    content = local.read_bytes()
    rel = local.relative_to(Path(get_edgar_data_directory()))
    if rel.suffix == ".gz":
        content = gzip.decompress(content)
        rel = rel.with_suffix("")          # store the canonical, uncompressed form

    with conn.transaction():               # all-or-nothing
        row = conn.execute(
            """INSERT INTO raw.filing
                 (company_id, accession_no, form_type, published_at, source_url, parser_version)
               VALUES (%s, %s, %s, %s, %s, %s)
               ON CONFLICT (accession_no) DO NOTHING
               RETURNING filing_id""",
            (company_id, filing.accession_number, filing.form_type,
             filing.filing_date,           # midnight stand-in, see note below
             "<filing url>", "v0"),
        ).fetchone()
        if row is None:
            return                         # already ingested
        conn.execute(
            """INSERT INTO raw.filing_store
                 (filing_id, content, content_sha256, local_rel_path)
               VALUES (%s, %s, %s, %s)""",
            (row[0], content, hashlib.sha256(content).digest(), rel.as_posix()),
        )
        # insert sections, facts, and statement lines here, in the same transaction