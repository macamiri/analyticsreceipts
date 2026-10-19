"""PLANTED BROKEN COMPILER: a control, never a product path.

It compiles exactly like the real compiler except that it drops convention C1: the dataset source is
`raw_lines` as loaded, so the duplicated 2010-12-01..09 window is counted twice. The canary and the
December 2010 fixture must FAIL when the server runs with it. If they pass, the eval cannot see a
broken semantic layer, and its other results mean nothing.

Used only through `python -m analyticsreceipts.control_server --bug drop_c1` (the fixture harness's control
run) or by passing compile_fn explicitly. The product server has no switch for it. Receipts produced with it
carry compiler="planted:drop_c1" and a model hash that is not the governed model's.
"""

import dataclasses

from .compiler import compile_request

BUG_NAME = "drop_c1"


def compile_request_broken(model, req):
    broken = dataclasses.replace(model, dataset_source="SELECT * FROM raw_lines")
    return compile_request(broken, req)


compile_request_broken.compiler_id = f"planted:{BUG_NAME}"
