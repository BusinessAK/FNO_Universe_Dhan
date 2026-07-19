"""One connection manager for DuckDB (R2). Replaces ad-hoc duckdb.connect
call sites as modules get touched; context-managed so Streamlit/daemon
runtimes can't leak file locks."""
from contextlib import contextmanager

import duckdb

from vanguard.config.paths import DB


@contextmanager
def connect(read_only: bool = True, path=None):
    con = duckdb.connect(str(path or DB), read_only=read_only)
    try:
        yield con
    finally:
        con.close()
