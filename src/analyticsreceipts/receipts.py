"""The receipt JSON Schema (`receipt.schema.json`, shipped in the wheel) and a validator."""

import json
from functools import lru_cache
from importlib import resources


@lru_cache(maxsize=1)
def receipt_schema():
    return json.loads(resources.files(__package__).joinpath("receipt.schema.json").read_text())


def validate_receipt(receipt):
    """Raises jsonschema.ValidationError if the receipt does not match the schema."""
    import jsonschema

    jsonschema.validate(receipt, receipt_schema())
