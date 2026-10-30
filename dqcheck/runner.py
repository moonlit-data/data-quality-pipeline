"""Load the sources into DuckDB and run every check, collecting results."""
from __future__ import annotations

import datetime as dt
import decimal
import time
from dataclasses import asdict, dataclass, field

import duckdb

from .checks import CHECKS, CheckError, q
from .config import Config

SAMPLE_ROWS = 5


@dataclass
class CheckResult:
    name: str
    type: str
    severity: str
    status: str                 # pass | fail | error
    failing: int | None
    total: int | None
    unit: str
    note: str
    sql: str
    sample_columns: list = field(default_factory=list)
    sample: list = field(default_factory=list)
    seconds: float = 0.0

    @property
    def failing_pct(self):
        if self.failing is None or not self.total or self.unit != "rows":
            return None
        return round(100 * self.failing / self.total, 2)

    def to_dict(self):
        d = asdict(self)
        d["failing_pct"] = self.failing_pct
        return d


@dataclass
class RunResult:
    name: str
    started: str
    sources: dict
    results: list

    def counts(self):
        c = {"pass": 0, "fail_error": 0, "fail_warn": 0, "error": 0}
        for r in self.results:
            if r.status == "pass":
                c["pass"] += 1
            elif r.status == "error":
                c["error"] += 1
            else:
                c["fail_error" if r.severity == "error" else "fail_warn"] += 1
        return c

    def ok(self, fail_on="error"):
        """True if nothing blocks: errors always block; warnings block only with fail_on='warn'."""
        c = self.counts()
        if c["error"] or c["fail_error"]:
            return False
        return not (fail_on == "warn" and c["fail_warn"])


def plain(v):
    """Make a sample value printable and JSON-safe."""
    if v is None or isinstance(v, (bool, int, str)):
        return v
    if isinstance(v, float):
        return round(v, 4)
    if isinstance(v, decimal.Decimal):
        return float(v)
    if isinstance(v, (dt.date, dt.datetime, dt.time)):
        return v.isoformat(sep=" ") if isinstance(v, dt.datetime) else v.isoformat()
    return str(v)


def load_sources(con, config: Config) -> dict:
    sizes = {}
    for name, src in config.sources.items():
        if not src.path.exists():
            raise FileNotFoundError(f"source '{name}': file not found: {src.path}")
        path = src.path.as_posix().replace("'", "''")
        if src.path.suffix.lower() == ".parquet":
            con.execute(f"CREATE OR REPLACE TABLE {q(name)} AS SELECT * FROM read_parquet('{path}')").fetchall()
        else:
            types = ""
            if src.types:
                spec = ", ".join(f"'{c}': '{t}'" for c, t in src.types.items())
                types = f", types = {{{spec}}}"
            con.execute(f"CREATE OR REPLACE TABLE {q(name)} AS "
                        f"SELECT * FROM read_csv('{path}', header = true{types})").fetchall()
        sizes[name] = con.execute(f"SELECT COUNT(*) FROM {q(name)}").fetchall()[0][0]
    return sizes


def run_check(con, spec) -> CheckResult:
    start = time.perf_counter()
    try:
        out = CHECKS[spec.type](con, spec.options)
        cur = con.execute(f"SELECT * FROM ({out.sql}) AS sample LIMIT {SAMPLE_ROWS}")
        cols = [d[0] for d in cur.description]
        sample = [[plain(v) for v in row] for row in cur.fetchall()] if out.failing else []
        status = "pass" if out.failing == 0 else "fail"
        return CheckResult(spec.name, spec.type, spec.severity, status, out.failing, out.total, out.unit,
                           out.note, out.sql, cols if sample else [], sample, round(time.perf_counter() - start, 3))
    except (CheckError, duckdb.Error) as e:
        return CheckResult(spec.name, spec.type, spec.severity, "error", None, None, "rows",
                           str(e).splitlines()[0], "", seconds=round(time.perf_counter() - start, 3))


def run(config: Config, con=None) -> RunResult:
    con = con or duckdb.connect()
    started = dt.datetime.now().replace(microsecond=0).isoformat(sep=" ")
    sizes = load_sources(con, config)
    results = [run_check(con, spec) for spec in config.checks]
    return RunResult(config.name, started, sizes, results)
