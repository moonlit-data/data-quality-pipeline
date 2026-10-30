"""Write the run results as Markdown, HTML and JSON."""
from __future__ import annotations

import html
import json
import pathlib

from .runner import RunResult

LABEL = {"pass": "PASS", "fail_error": "FAIL", "fail_warn": "WARN", "error": "ERROR"}
ICON = {"pass": "✓", "fail_error": "✕", "fail_warn": "!", "error": "⚠"}


def kind(r):
    if r.status == "pass":
        return "pass"
    if r.status == "error":
        return "error"
    return "fail_error" if r.severity == "error" else "fail_warn"


def fmt_count(r):
    if r.failing is None:
        return "-"
    if r.unit == "table":
        return "yes" if r.failing else "no"
    return f"{r.failing:,}"


def summary_line(run: RunResult):
    c = run.counts()
    return (f"{len(run.results)} checks: {c['pass']} passed, {c['fail_error']} failed, "
            f"{c['fail_warn']} warnings, {c['error']} could not run")


def md_cell(v):
    return str(v).replace("|", "\\|").replace("\n", " ")


def to_markdown(run: RunResult) -> str:
    out = [f"# {run.name}", "", f"Run {run.started}. {summary_line(run)}.", "",
           "Sources: " + ", ".join(f"`{k}` ({v:,} rows)" for k, v in run.sources.items()), "",
           "| Status | Check | Type | Failing | Checked | % |", "|---|---|---|---:|---:|---:|"]
    order = {"error": 0, "fail_error": 1, "fail_warn": 2, "pass": 3}
    ranked = sorted(run.results, key=lambda r: order[kind(r)])
    for r in ranked:
        pct = "" if r.failing_pct is None else f"{r.failing_pct}%"
        total = "" if r.total is None else f"{r.total:,}"
        out.append(f"| {ICON[kind(r)]} {LABEL[kind(r)]} | {md_cell(r.name)} | `{r.type}` | {fmt_count(r)} | {total} | {pct} |")
    details = [r for r in ranked if r.status != "pass"]
    if details:
        out += ["", "## Details", ""]
    for r in details:
        out += [f"### {ICON[kind(r)]} {r.name}", ""]
        if r.note:
            out += [r.note, ""]
        if r.sample:
            out.append("| " + " | ".join(md_cell(c) for c in r.sample_columns) + " |")
            out.append("|" + "---|" * len(r.sample_columns))
            for row in r.sample:
                out.append("| " + " | ".join(md_cell("" if v is None else v) for v in row) + " |")
            shown = min(len(r.sample), r.failing or 0)
            out += ["", f"First {shown} of {fmt_count(r)}.", ""]
        if r.sql:
            out += ["<details><summary>SQL</summary>", "", "```sql", r.sql, "```", "", "</details>", ""]
    return "\n".join(out) + "\n"


CSS = """
:root { color-scheme: light; --page:#f9f9f7; --surface:#fcfcfb; --ink:#0b0b0b; --ink2:#52514e; --line:#e1e0d9;
  --good:#0ca30c; --warning:#fab219; --critical:#d03b3b; --code:#f0efec; }
@media (prefers-color-scheme: dark) { :root { color-scheme: dark; --page:#0d0d0d; --surface:#1a1a19;
  --ink:#f0efec; --ink2:#c3c2b7; --line:#2c2c2a; --code:#262624; } }
body { margin:0; background:var(--page); color:var(--ink); font-family: system-ui, -apple-system, "Segoe UI", sans-serif; }
.wrap { max-width:1100px; margin:0 auto; padding:28px 24px 48px; }
h1 { font-size:22px; margin:0 0 4px; } h2 { font-size:16px; margin:28px 0 8px; }
.sub { color:var(--ink2); font-size:14px; margin-bottom:16px; }
table { border-collapse:collapse; width:100%; font-size:13px; background:var(--surface); font-variant-numeric: tabular-nums; }
th, td { text-align:left; padding:6px 8px; border-bottom:1px solid var(--line); vertical-align:top; }
th { color:var(--ink2); font-weight:600; } td.n { text-align:right; }
.badge { display:inline-flex; gap:6px; align-items:center; font-weight:600; white-space:nowrap; }
.dot { width:10px; height:10px; border-radius:50%; display:inline-block; }
.pass .dot { background:var(--good); } .fail_error .dot, .error .dot { background:var(--critical); }
.fail_warn .dot { background:var(--warning); }
.card { background:var(--surface); border:1px solid var(--line); border-radius:10px; padding:12px 16px; margin:12px 0; }
.note { color:var(--ink2); font-size:13px; margin:4px 0 8px; }
pre { background:var(--code); padding:10px; border-radius:8px; overflow-x:auto; font-size:12px; }
.sample { overflow-x:auto; }
"""


def to_html(run: RunResult) -> str:
    e = html.escape
    rows = []
    order = {"error": 0, "fail_error": 1, "fail_warn": 2, "pass": 3}
    ranked = sorted(run.results, key=lambda r: order[kind(r)])
    for r in ranked:
        k = kind(r)
        pct = "" if r.failing_pct is None else f"{r.failing_pct}%"
        total = "" if r.total is None else f"{r.total:,}"
        rows.append(f"<tr><td><span class='badge {k}'><span class='dot'></span>{ICON[k]} {LABEL[k]}</span></td>"
                    f"<td>{e(r.name)}</td><td><code>{e(r.type)}</code></td><td class='n'>{e(fmt_count(r))}</td>"
                    f"<td class='n'>{total}</td><td class='n'>{pct}</td></tr>")
    cards = []
    for r in [r for r in ranked if r.status != "pass"]:
        k = kind(r)
        sample = ""
        if r.sample:
            head = "".join(f"<th>{e(str(c))}</th>" for c in r.sample_columns)
            body = "".join("<tr>" + "".join(f"<td>{e('' if v is None else str(v))}</td>" for v in row) + "</tr>"
                           for row in r.sample)
            sample = f"<div class='sample'><table><tr>{head}</tr>{body}</table></div>"
        sql = f"<details><summary>SQL</summary><pre>{e(r.sql)}</pre></details>" if r.sql else ""
        cards.append(f"<div class='card'><div class='badge {k}'><span class='dot'></span>{ICON[k]} {LABEL[k]}"
                     f" &nbsp; {e(r.name)}</div><div class='note'>{e(r.note)}</div>{sample}{sql}</div>")
    sources = ", ".join(f"<code>{e(k)}</code> ({v:,} rows)" for k, v in run.sources.items())
    return (f"<!doctype html><html lang='en'><head><meta charset='utf-8'>"
            f"<meta name='viewport' content='width=device-width, initial-scale=1'><title>{e(run.name)}</title>"
            f"<style>{CSS}</style></head><body><div class='wrap'><h1>{e(run.name)}</h1>"
            f"<div class='sub'>Run {e(run.started)}. {e(summary_line(run))}.<br>Sources: {sources}</div>"
            f"<table><tr><th>Status</th><th>Check</th><th>Type</th><th>Failing</th><th>Checked</th><th>%</th></tr>"
            f"{''.join(rows)}</table>"
            + (f"<h2>Details</h2>{''.join(cards)}" if cards else "")
            + "</div></body></html>")


def write(run: RunResult, out_dir) -> dict:
    out = pathlib.Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    paths = {"markdown": out / "report.md", "html": out / "report.html", "json": out / "results.json"}
    paths["markdown"].write_text(to_markdown(run), encoding="utf-8")
    paths["html"].write_text(to_html(run), encoding="utf-8")
    payload = {"name": run.name, "started": run.started, "sources": run.sources, "summary": run.counts(),
               "results": [r.to_dict() for r in run.results]}
    paths["json"].write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return paths
