"""Build the read-only DuckDB warehouse from the UCI Online Retail II workbook.

Both yearly sheets are loaded exactly as delivered into one table, `raw_lines`, with the sheet name
and row number kept. Nothing is cleaned or de-duplicated here: the two sheets share an identical
window (2010-12-01 to 2010-12-09), and removing it is a rule of the semantic model, not of the load.
That keeps the raw-SQL arm of the eval honest: it sees the data a warehouse would really hold.

Usage: python -m analyticsreceipts.load <online_retail_II.xlsx> <out.duckdb>
"""

import csv
import hashlib
import os
import sys
import tempfile

import duckdb

EXPECTED_XLSX_SHA256 = "bcbe73b35f5b7babf197fb0cb983a11f5d9ff929078d4aa53d171b1f2df2e980"


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _xlsx_to_csv(xlsx, out_csv):
    import openpyxl  # only needed to build the warehouse

    wb = openpyxl.load_workbook(xlsx, read_only=True, data_only=True)
    with open(out_csv, "w", newline="") as f:
        w = csv.writer(f)
        for ws in wb.worksheets:
            rows = ws.iter_rows(values_only=True)
            next(rows)  # header
            n = 0
            for r in rows:
                if all(v is None for v in r):
                    continue
                n += 1
                inv, code, desc, qty, ts, price, cust, country = r[:8]
                w.writerow([ws.title, n, inv, code, desc, qty,
                            ts.isoformat(sep=" ") if ts is not None else None,
                            price, "" if cust is None else int(cust), country])


def build(xlsx, out_db, check_sha=True):
    digest = sha256_file(xlsx)
    if check_sha and digest != EXPECTED_XLSX_SHA256:
        raise SystemExit(f"workbook sha256 {digest} != pinned {EXPECTED_XLSX_SHA256}")
    if os.path.exists(out_db):
        os.remove(out_db)
    with tempfile.TemporaryDirectory() as tmp:
        csv_path = os.path.join(tmp, "lines.csv")
        _xlsx_to_csv(xlsx, csv_path)
        con = duckdb.connect(out_db)
        con.execute(
            "CREATE TABLE raw_lines AS SELECT * FROM read_csv(?, header=false, columns={"
            "'source_sheet':'VARCHAR','row_in_sheet':'BIGINT','invoice':'VARCHAR','stock_code':'VARCHAR',"
            "'description':'VARCHAR','quantity':'BIGINT','invoice_ts':'TIMESTAMP','price':'DECIMAL(12,3)',"
            "'customer_id':'VARCHAR','country':'VARCHAR'}, nullstr='')",
            [csv_path],
        )
        con.execute("CREATE TABLE snapshot_meta AS SELECT ? AS xlsx_sha256, max(invoice_ts) AS max_invoice_ts, "
                    "count(*) AS raw_line_count FROM raw_lines", [digest])
        con.close()
    return digest


if __name__ == "__main__":
    print(build(sys.argv[1], sys.argv[2]))
