"""Where the eval data lives (golden/, fixtures/, replays/). The data is part of the repository, not the wheel.

Order: $ANALYTICSRECEIPTS_ROOT; the source checkout this module sits in; the current directory. The first one
that holds golden/golden-v1.json wins. So an installed package run from a clone's root uses that clone.
"""

import os
from pathlib import Path

MARKER = Path("golden") / "golden-v1.json"


def _candidates():
    env = os.environ.get("ANALYTICSRECEIPTS_ROOT")
    if env:
        yield Path(env).resolve()
    yield Path(__file__).resolve().parents[2]
    yield Path.cwd().resolve()


def find_root():
    """The eval-data root, or None when there is none (the package is still usable as a grader/server)."""
    return next((c for c in _candidates() if (c / MARKER).exists()), None)


def data_root():
    root = find_root()
    if root is None:
        raise SystemExit("analyticsreceipts: eval data (golden/, fixtures/) not found. Run from the root of a clone "
                         "of the repository, or set ANALYTICSRECEIPTS_ROOT to it.")
    return root
