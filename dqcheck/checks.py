"""The checks. Each one turns its options into a SQL query that returns the failing rows.

Every check returns an Outcome: how many units failed, out of how many checked, and the SQL that lists
them (the report shows a sample and the query, so any finding can be reproduced by hand).
Edge-case rules are written next to each check and in docs/checks.md.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

TEXT_TYPES = ("VARCHAR", "TEXT", "STRING", "CHAR", "BPCHAR")


class CheckError(Exception):
    """The check could not run (for example a column that does not exist)."""


@dataclass
class Outcome:
    failing: int          # failing rows (or groups / tables, see `unit`)
    total: int | None     # rows checked
    unit: str             # what `failing` counts
    sql: str              # query returning the failing rows
    note: str = ""        # extra context for the report


# ---- helpers -------------------------------------------------------------------------------------

def q(name: str) -> str:
    """Quote an identifier."""
    return '"' + str(name).replace('"', '""') + '"'


def lit(value) -> str:
    """A SQL literal for a config value (strings are escaped, numbers kept as numbers)."""
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, (int, float)):
        return repr(value)
    if isinstance(value, (dt.date, dt.datetime)):
        return f"'{value.isoformat()}'"
    return "'" + str(value).replace("'", "''") + "'"


def scalar(con, sql):
    return con.execute(sql).fetchall()[0][0]


def columns_of(con, table) -> dict:
    rows = con.execute(f"DESCRIBE {q(table)}").fetchall()
    return {r[0]: r[1] for r in rows}


def need(con, table, names):
    have = columns_of(con, table)
    missing = [n for n in names if n not in have]
    if missing:
        raise CheckError(f"column(s) {', '.join(missing)} not found in '{table}' "
                         f"(columns: {', '.join(have)})")
    return have


def count(con, sql) -> int:
    return scalar(con, f"SELECT COUNT(*) FROM ({sql}) AS failing")


def rows(con, table) -> int:
    return scalar(con, f"SELECT COUNT(*) FROM {q(table)}")


def not_null_all(cols, alias="") -> str:
    p = f"{alias}." if alias else ""
    return " AND ".join(f"{p}{q(c)} IS NOT NULL" for c in cols)


# ---- checks --------------------------------------------------------------------------------------

def not_null(con, o) -> Outcome:
    """Rows where any listed column is NULL. Text that is empty or only spaces counts as missing
    unless treat_blank_as_null is false."""
    t, cols = o["table"], o["columns"]
    types = need(con, t, cols)
    blank = o.get("treat_blank_as_null", True)
    conds = []
    for c in cols:
        if blank and types[c].upper().startswith(TEXT_TYPES):
            conds.append(f"({q(c)} IS NULL OR trim({q(c)}) = '')")
        else:
            conds.append(f"{q(c)} IS NULL")
    sql = f"SELECT * FROM {q(t)} WHERE " + " OR ".join(conds)
    per_col = ", ".join(f"{c}: {scalar(con, f'SELECT COUNT(*) FROM {q(t)} WHERE {cond}')}"
                        for c, cond in zip(cols, conds))
    return Outcome(count(con, sql), rows(con, t), "rows", sql, f"missing per column - {per_col}")


def unique(con, o) -> Outcome:
    """Rows whose key appears more than once (all copies are listed). Rows with a NULL in any key
    column are left out: a missing key is a not_null problem, not a duplicate."""
    t, cols = o["table"], o["columns"]
    need(con, t, cols)
    keys = ", ".join(q(c) for c in cols)
    sql = (f"SELECT * FROM (SELECT *, COUNT(*) OVER (PARTITION BY {keys}) AS dup_count FROM {q(t)} "
           f"WHERE {not_null_all(cols)}) AS k WHERE dup_count > 1 ORDER BY {keys}")
    groups = scalar(con, f"SELECT COUNT(*) FROM (SELECT DISTINCT {keys} FROM ({sql}) AS d) AS g")
    skipped = scalar(con, f"SELECT COUNT(*) FROM {q(t)} WHERE NOT ({not_null_all(cols)})")
    note = f"{groups} duplicated key value(s)"
    if skipped:
        note += f"; {skipped} row(s) with a NULL key not checked"
    return Outcome(count(con, sql), rows(con, t), "rows", sql, note)


def present(c) -> str:
    """The value is there: not NULL and, for text, not blank. Missing values belong to not_null."""
    return f"NULLIF(trim(CAST({q(c)} AS VARCHAR)), '') IS NOT NULL"


def accepted_values(con, o) -> Outcome:
    """Rows whose value is not in the list. NULL and blank text are not checked here (use not_null).
    case_sensitive: false compares upper-cased text."""
    t, c, values = o["table"], o["column"], o["values"]
    need(con, t, [c])
    if o.get("case_sensitive", True):
        cond = f"{q(c)} NOT IN ({', '.join(lit(v) for v in values)})"
    else:
        cond = (f"upper(CAST({q(c)} AS VARCHAR)) NOT IN "
                f"({', '.join(lit(str(v).upper()) for v in values)})")
    sql = f"SELECT * FROM {q(t)} WHERE {present(c)} AND {cond}"
    return Outcome(count(con, sql), rows(con, t), "rows", sql)


def range_check(con, o) -> Outcome:
    """Rows outside [min, max]. Bounds are inclusive unless exclusive_min / exclusive_max is true.
    NULL is not checked here."""
    t, c = o["table"], o["column"]
    need(con, t, [c])
    conds = []
    if "min" in o and o["min"] is not None:
        conds.append(f"{q(c)} {'<=' if o.get('exclusive_min') else '<'} {lit(o['min'])}")
    if "max" in o and o["max"] is not None:
        conds.append(f"{q(c)} {'>=' if o.get('exclusive_max') else '>'} {lit(o['max'])}")
    sql = f"SELECT * FROM {q(t)} WHERE {q(c)} IS NOT NULL AND ({' OR '.join(conds)})"
    return Outcome(count(con, sql), rows(con, t), "rows", sql)


def regex(con, o) -> Outcome:
    """Rows whose text does not match the pattern. The whole value must match unless
    full_match is false. NULL and blank text are not checked here (use not_null)."""
    t, c = o["table"], o["column"]
    need(con, t, [c])
    fn = "regexp_full_match" if o.get("full_match", True) else "regexp_matches"
    sql = (f"SELECT * FROM {q(t)} WHERE {present(c)} "
           f"AND NOT {fn}(CAST({q(c)} AS VARCHAR), {lit(o['pattern'])})")
    return Outcome(count(con, sql), rows(con, t), "rows", sql)


def foreign_key(con, o) -> Outcome:
    """Child rows whose key has no match in the parent table. Child rows with a NULL in the key
    are not checked; duplicates in the parent do not matter (NOT EXISTS)."""
    t, cols, ref, ref_cols = o["table"], o["columns"], o["ref_table"], o["ref_columns"]
    need(con, t, cols)
    need(con, ref, ref_cols)
    match = " AND ".join(f"p.{q(rc)} = c.{q(cc)}" for cc, rc in zip(cols, ref_cols))
    sql = (f"SELECT c.* FROM {q(t)} AS c WHERE {not_null_all(cols, 'c')} "
           f"AND NOT EXISTS (SELECT 1 FROM {q(ref)} AS p WHERE {match})")
    return Outcome(count(con, sql), rows(con, t), "rows", sql)


def reconcile(con, o) -> Outcome:
    """Parent rows whose amount differs from the sum of their child rows by more than the tolerance
    (a difference exactly equal to the tolerance passes). A parent with no children is compared with 0.
    child_amount may be an expression, for example quantity * unit_price."""
    parent, child = o["parent"], o["child"]
    pk, ck = o["parent_key"], o["child_key"]
    need(con, parent, pk + [o["parent_amount"]])
    need(con, child, ck)
    tol = float(o.get("tolerance", 0.01))
    keys_out = ", ".join(f"{q(c)} AS _k{i}" for i, c in enumerate(ck))
    join = " AND ".join(f"ch._k{i} = p.{q(c)}" for i, c in enumerate(pk))
    amount = f"p.{q(o['parent_amount'])}"
    sql = (f"WITH ch AS (SELECT {keys_out}, SUM({o['child_amount']}) AS _child_total FROM {q(child)} "
           f"GROUP BY ALL) "
           f"SELECT p.*, COALESCE(ch._child_total, 0) AS child_total, "
           f"{amount} - COALESCE(ch._child_total, 0) AS difference "
           f"FROM {q(parent)} AS p LEFT JOIN ch ON {join} "
           f"WHERE {amount} IS NOT NULL "
           f"AND ABS(CAST({amount} AS DOUBLE) - CAST(COALESCE(ch._child_total, 0) AS DOUBLE)) > {tol!r} + 1e-9")
    return Outcome(count(con, sql), rows(con, parent), "rows", sql)


def duplicate_transactions(con, o) -> Outcome:
    """Rows that repeat an earlier row with the same keys within window_minutes (inclusive).
    Only the later copies are listed; the first one of each run is kept as the original."""
    t, keys, ts, window = o["table"], o["keys"], o["timestamp"], float(o["window_minutes"])
    need(con, t, keys + [ts])
    part = ", ".join(q(k) for k in keys)
    sql = (f"SELECT * EXCLUDE (_prev_ts), date_diff('second', _prev_ts, {q(ts)}) / 60.0 AS minutes_after_previous "
           f"FROM (SELECT *, LAG({q(ts)}) OVER (PARTITION BY {part} ORDER BY {q(ts)}) AS _prev_ts "
           f"FROM {q(t)} WHERE {not_null_all(keys + [ts])}) AS x "
           f"WHERE _prev_ts IS NOT NULL AND date_diff('second', _prev_ts, {q(ts)}) <= {window * 60!r}")
    return Outcome(count(con, sql), rows(con, t), "rows", sql)


def outliers(con, o) -> Outcome:
    """Values far from the typical value of their group, by the robust z-score
    0.6745 * (x - median) / MAD (Iglewicz and Hoaglin). If MAD is 0 the mean absolute deviation is used
    instead (x - median) / (1.2533 * meanAD); if that is 0 too, every value is equal and nothing is flagged.
    Groups smaller than min_group_size (default 10) are skipped. NULL is ignored."""
    t, c = o["table"], o["column"]
    groups = o.get("group_by") or []
    need(con, t, [c] + groups)
    threshold = float(o.get("threshold", 3.5))
    min_n = int(o.get("min_group_size", 10))
    g = ", ".join(q(x) for x in groups) if groups else "_grp"
    grp_expr = "" if groups else ", 'all' AS _grp"
    using = ", ".join(q(x) for x in groups) if groups else "_grp"
    sql = (f"WITH base AS (SELECT *, CAST({q(c)} AS DOUBLE) AS _x{grp_expr} FROM {q(t)} WHERE {q(c)} IS NOT NULL), "
           f"med AS (SELECT {g}, median(_x) AS _med, COUNT(*) AS _n FROM base GROUP BY ALL), "
           f"dev AS (SELECT {g}, median(abs(b._x - m._med)) AS _mad, avg(abs(b._x - m._med)) AS _meanad "
           f"FROM base AS b JOIN med AS m USING ({using}) GROUP BY ALL), "
           f"scored AS (SELECT b.*, m._med AS group_median, m._n AS _n, "
           f"CASE WHEN d._mad > 0 THEN 0.6745 * (b._x - m._med) / d._mad "
           f"WHEN d._meanad > 0 THEN (b._x - m._med) / (1.2533 * d._meanad) ELSE 0 END AS robust_z "
           f"FROM base AS b JOIN med AS m USING ({using}) JOIN dev AS d USING ({using})) "
           f"SELECT * EXCLUDE (_x, _n{', _grp' if not groups else ''}) FROM scored "
           f"WHERE _n >= {min_n} AND abs(robust_z) > {threshold!r} ORDER BY abs(robust_z) DESC")
    small = scalar(con, f"SELECT COUNT(*) FROM (SELECT {g} FROM (SELECT *{grp_expr} FROM {q(t)} "
                        f"WHERE {q(c)} IS NOT NULL) AS s GROUP BY ALL HAVING COUNT(*) < {min_n}) AS sm")
    note = f"threshold |z| > {threshold}" + (f"; {small} group(s) under {min_n} rows skipped" if small else "")
    return Outcome(count(con, sql), rows(con, t), "rows", sql, note)


def row_count(con, o) -> Outcome:
    """The table has at least min and at most max rows."""
    t = o["table"]
    n = rows(con, t)
    bad = ("min" in o and n < o["min"]) or ("max" in o and n > o["max"])
    limits = " and ".join(f"{k} {o[k]}" for k in ("min", "max") if k in o)
    return Outcome(int(bad), n, "table", f"SELECT COUNT(*) AS rows FROM {q(t)}", f"{n} rows ({limits})")


def freshness(con, o) -> Outcome:
    """The newest value of the column is at most max_age_days before as_of (default: today)."""
    t, c = o["table"], o["column"]
    need(con, t, [c])
    as_of = o.get("as_of") or dt.date.today()
    if isinstance(as_of, str):
        as_of = dt.date.fromisoformat(as_of)
    latest = scalar(con, f"SELECT CAST(MAX({q(c)}) AS DATE) FROM {q(t)}")
    age = None if latest is None else (as_of - latest).days
    bad = age is None or age > o["max_age_days"]
    note = "table is empty" if latest is None else f"newest {latest}, {age} day(s) before {as_of}"
    return Outcome(int(bad), rows(con, t), "table", f"SELECT MAX({q(c)}) AS newest FROM {q(t)}", note)


def custom_sql(con, o) -> Outcome:
    """Any query; every row it returns is a failure."""
    sql = o["sql"].strip().rstrip(";")
    total = rows(con, o["table"]) if o.get("table") else None
    return Outcome(count(con, sql), total, "rows", sql)


CHECKS = {
    "not_null": not_null,
    "unique": unique,
    "accepted_values": accepted_values,
    "range": range_check,
    "regex": regex,
    "foreign_key": foreign_key,
    "reconcile": reconcile,
    "duplicate_transactions": duplicate_transactions,
    "outliers": outliers,
    "row_count": row_count,
    "freshness": freshness,
    "custom_sql": custom_sql,
}
