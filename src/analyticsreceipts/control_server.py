"""CONTROL entry point: the MCP server with a planted broken compiler. Never a product path.

Used by the fixture harness to prove the eval can see a broken semantic layer (the canary and the
December 2010 fixture must FAIL). Receipts say compiler="planted:<bug>".

Usage: python -m analyticsreceipts.control_server --bug drop_c1 [--db ...] [--model ...]
"""

import argparse
import os

from .broken import BUG_NAME, compile_request_broken
from .server import build_server


def main(argv=None):
    ap = argparse.ArgumentParser(prog="analyticsreceipts.control_server")
    ap.add_argument("--bug", required=True, choices=[BUG_NAME])
    ap.add_argument("--db", default=os.environ.get("ANALYTICSRECEIPTS_DB"))
    ap.add_argument("--model", default=os.environ.get("ANALYTICSRECEIPTS_MODEL"))
    a = ap.parse_args(argv)
    build_server(db_path=a.db, model_path=a.model, compile_fn=compile_request_broken).run("stdio")


if __name__ == "__main__":
    main()
