"""Make a missing warehouse loud. Without ANALYTICSRECEIPTS_DB, every test that needs the DuckDB file is
skipped; a run that only says "N passed, M skipped" reads like a pass. This prints a banner at the start
and a summary at the end naming how many tests did not run, and how to build the warehouse."""

import os
from pathlib import Path

REASON = "ANALYTICSRECEIPTS_DB not built"
HOW = ("python -m analyticsreceipts.load online_retail_II.xlsx retail.duckdb && "
       "export ANALYTICSRECEIPTS_DB=$PWD/retail.duckdb")


def _db_ok():
    db = os.environ.get("ANALYTICSRECEIPTS_DB")
    return bool(db) and Path(db).exists()


def pytest_report_header(config):
    if not _db_ok():
        return [f"WARNING: ANALYTICSRECEIPTS_DB is not set or missing. Warehouse tests will be SKIPPED. Build it: {HOW}"]
    return [f"warehouse: {os.environ['ANALYTICSRECEIPTS_DB']}"]


def pytest_terminal_summary(terminalreporter):
    skipped = [r for r in terminalreporter.stats.get("skipped", [])
               if isinstance(r.longrepr, tuple) and REASON in str(r.longrepr[2])]
    if skipped:
        terminalreporter.write_sep("!", f"{len(skipped)} WAREHOUSE TESTS DID NOT RUN (ANALYTICSRECEIPTS_DB not built)",
                                   red=True, bold=True)
        terminalreporter.write_line("This is NOT a full pass. Build the warehouse and re-run:")
        terminalreporter.write_line(f"  {HOW}")
