import os
import psycopg
from psycopg.rows import dict_row
from dotenv import load_dotenv

load_dotenv()

def connect():
    # autocommit: each statement commits immediately unless wrapped in
    # `with conn.transaction():`, which makes the whole block atomic.
    return psycopg.connect(os.environ["DATABASE_URL"], row_factory=dict_row, autocommit=True)