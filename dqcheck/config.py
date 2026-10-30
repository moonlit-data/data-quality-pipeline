"""Read and validate a check configuration (YAML).

A configuration names the data sources and lists the checks. Mistakes in it (an unknown check type, a
missing option, a misspelled table) are reported all at once with the check they belong to, before any
data is read.
"""
from __future__ import annotations

import pathlib
from dataclasses import dataclass, field

import yaml

SEVERITIES = ("error", "warn")

# check type -> (required options, optional options)
CHECK_OPTIONS = {
    "not_null": ({"table", "columns"}, {"treat_blank_as_null"}),
    "unique": ({"table", "columns"}, set()),
    "accepted_values": ({"table", "column", "values"}, {"case_sensitive"}),
    "range": ({"table", "column"}, {"min", "max", "exclusive_min", "exclusive_max"}),
    "regex": ({"table", "column", "pattern"}, {"full_match"}),
    "foreign_key": ({"table", "columns", "ref_table", "ref_columns"}, set()),
    "reconcile": ({"parent", "parent_key", "parent_amount", "child", "child_key", "child_amount"}, {"tolerance"}),
    "duplicate_transactions": ({"table", "keys", "timestamp", "window_minutes"}, set()),
    "outliers": ({"table", "column"}, {"group_by", "threshold", "min_group_size"}),
    "row_count": ({"table"}, {"min", "max"}),
    "freshness": ({"table", "column", "max_age_days"}, {"as_of"}),
    "custom_sql": ({"sql"}, {"table"}),
}
COMMON = {"type", "name", "severity", "description"}


class ConfigError(ValueError):
    """The configuration cannot be used. `problems` lists every problem found."""

    def __init__(self, problems):
        self.problems = problems
        super().__init__("invalid configuration:\n  - " + "\n  - ".join(problems))


@dataclass
class Source:
    name: str
    path: pathlib.Path
    types: dict = field(default_factory=dict)


@dataclass
class CheckSpec:
    type: str
    name: str
    severity: str
    options: dict
    description: str = ""


@dataclass
class Config:
    name: str
    sources: dict
    checks: list
    base_dir: pathlib.Path


def default_name(spec):
    t = spec["type"]
    target = spec.get("table") or spec.get("parent") or ""
    detail = spec.get("columns") or spec.get("column") or spec.get("keys") or ""
    if isinstance(detail, list):
        detail = ", ".join(detail)
    return f"{t}: {target}" + (f" ({detail})" if detail else "")


def parse(data: dict, base_dir: pathlib.Path) -> Config:
    problems = []
    if not isinstance(data, dict):
        raise ConfigError(["the file must contain a mapping with 'sources' and 'checks'"])
    sources = {}
    for name, src in (data.get("sources") or {}).items():
        if isinstance(src, str):
            src = {"path": src}
        if not isinstance(src, dict) or "path" not in src:
            problems.append(f"source '{name}': needs a 'path'")
            continue
        sources[name] = Source(name, (base_dir / src["path"]).resolve(), dict(src.get("types") or {}))
    if not sources:
        problems.append("no sources defined")

    checks = []
    for i, spec in enumerate(data.get("checks") or [], 1):
        where = f"check {i}"
        if not isinstance(spec, dict) or "type" not in spec:
            problems.append(f"{where}: needs a 'type'")
            continue
        t = spec["type"]
        where = f"check {i} ({spec.get('name') or t})"
        if t not in CHECK_OPTIONS:
            problems.append(f"{where}: unknown type '{t}' (known: {', '.join(sorted(CHECK_OPTIONS))})")
            continue
        required, optional = CHECK_OPTIONS[t]
        missing = sorted(required - spec.keys())
        unknown = sorted(spec.keys() - required - optional - COMMON)
        if missing:
            problems.append(f"{where}: missing {', '.join(missing)}")
        if unknown:
            problems.append(f"{where}: unknown option {', '.join(unknown)}")
        severity = spec.get("severity", "error")
        if severity not in SEVERITIES:
            problems.append(f"{where}: severity must be one of {', '.join(SEVERITIES)}")
        for key in ("table", "parent", "child", "ref_table"):
            if key in spec and spec[key] not in sources:
                problems.append(f"{where}: {key} '{spec[key]}' is not a defined source")
        for key in ("columns", "keys", "parent_key", "child_key", "ref_columns", "group_by"):
            if key in spec and not (isinstance(spec[key], list) and all(isinstance(c, str) for c in spec[key])):
                problems.append(f"{where}: '{key}' must be a list of column names")
        if t == "range" and "min" not in spec and "max" not in spec:
            problems.append(f"{where}: give 'min', 'max' or both")
        if t == "row_count" and "min" not in spec and "max" not in spec:
            problems.append(f"{where}: give 'min', 'max' or both")
        if t == "foreign_key" and len(spec.get("columns", [])) != len(spec.get("ref_columns", [])):
            problems.append(f"{where}: 'columns' and 'ref_columns' must have the same length")
        if t == "reconcile" and len(spec.get("parent_key", [])) != len(spec.get("child_key", [])):
            problems.append(f"{where}: 'parent_key' and 'child_key' must have the same length")
        options = {k: v for k, v in spec.items() if k not in COMMON}
        checks.append(CheckSpec(t, spec.get("name") or default_name(spec), severity, options,
                                spec.get("description", "")))
    if not checks and not problems:
        problems.append("no checks defined")
    if problems:
        raise ConfigError(problems)
    return Config(data.get("name", "Data quality report"), sources, checks, base_dir)


def load(path) -> Config:
    path = pathlib.Path(path)
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return parse(data, path.parent.resolve())
