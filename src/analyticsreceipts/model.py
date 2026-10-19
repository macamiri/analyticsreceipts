"""Load and validate an Ossie semantic model, and expose what the compiler and server need."""

import hashlib
import json
import re
from dataclasses import dataclass, field
from importlib import resources
from pathlib import Path

import jsonschema
import yaml

VENDOR = "analyticsreceipts"
TIME_GRAINS = ("day", "month", "quarter", "year")


@dataclass(frozen=True)
class Metric:
    name: str
    expression: str
    description: str
    synonyms: tuple
    instructions: str
    meta: dict


@dataclass(frozen=True)
class Dimension:
    name: str
    expression: str
    is_time: bool
    description: str = ""
    synonyms: tuple = ()


@dataclass
class SemanticModel:
    name: str
    sha256: str
    instructions: str
    dataset_name: str
    dataset_source: str
    fields: dict  # name -> SQL expression
    metrics: dict = field(default_factory=dict)  # name -> Metric
    dimensions: dict = field(default_factory=dict)  # name -> Dimension
    time_dimension: str = ""

    def metric_sql(self, name):
        """The metric expression with every `<dataset>.<field>` replaced by the field's expression."""
        expr = self.metrics[name].expression
        pat = re.compile(rf"\b{re.escape(self.dataset_name)}\.([A-Za-z_][A-Za-z0-9_]*)\b")

        def sub(m):
            f = m.group(1)
            if f not in self.fields:
                raise KeyError(f"metric {name} references unknown field {f}")
            return f"({self.fields[f]})"

        return pat.sub(sub, expr)


def _ansi(expr_obj):
    for d in expr_obj["dialects"]:
        if d["dialect"] == "ANSI_SQL":
            return d["expression"]
    raise ValueError("no ANSI_SQL expression")


def _ctx(obj):
    c = obj.get("ai_context") or {}
    if isinstance(c, str):
        return (), c
    return tuple(c.get("synonyms") or ()), c.get("instructions") or ""


def _packaged(name):
    """A data file shipped inside the installed package (wheel), or None in a source checkout."""
    p = resources.files("analyticsreceipts") / "data" / name
    return Path(str(p)) if p.is_file() else None


def schema_path():
    """The pinned Ossie JSON Schema: packaged copy if installed, else the repo's vendor/ copy."""
    for p in (_packaged("ossie-schema.json"), Path(__file__).resolve().parents[2] / "vendor" / "ossie" / "ossie-schema.json"):
        if p is not None and p.exists():
            return p
    raise FileNotFoundError("ossie-schema.json not found (package data or vendor/ossie/)")


def load(path):
    raw = Path(path).read_bytes()
    doc = yaml.safe_load(raw)
    schema = json.loads(schema_path().read_text())
    jsonschema.Draft202012Validator(schema).validate(doc)
    if len(doc["datasets"]) != 1:
        raise ValueError("M1 compiler supports exactly one dataset (no joins, so no fan-out)")
    ds = doc["datasets"][0]
    fields, dims, time_dim = {}, {}, ""
    for f in ds["fields"]:
        fields[f["name"]] = _ansi(f["expression"])
        if "dimension" in f:
            syn, _ = _ctx(f)
            is_time = bool(f["dimension"].get("is_time"))
            dims[f["name"]] = Dimension(f["name"], fields[f["name"]], is_time, f.get("description", ""), syn)
            if is_time:
                time_dim = f["name"]
    metrics = {}
    for m in doc.get("metrics", []):
        syn, instr = _ctx(m)
        meta = {}
        for ext in m.get("custom_extensions", []):
            if ext["vendor_name"] == VENDOR:
                meta = json.loads(ext["data"])
        metrics[m["name"]] = Metric(m["name"], _ansi(m["expression"]), m.get("description", ""), syn, instr, meta)
    _, instructions = _ctx(doc)
    return SemanticModel(doc["name"], hashlib.sha256(raw).hexdigest(), instructions, ds["name"], ds["source"],
                         fields, metrics, dims, time_dim)


def default_model_path():
    """The bundled Online Retail II model: packaged copy if installed, else the repo's model/ copy."""
    return _packaged("online_retail.ossie.yaml") or Path(__file__).resolve().parents[2] / "model" / "online_retail.ossie.yaml"
