"""Configuration validation, the runner and the command line."""
import json
import pathlib
import subprocess
import sys

import pytest

from dqcheck import ConfigError, parse, run

ROOT = pathlib.Path(__file__).resolve().parents[1]
DEMO = ROOT / "examples" / "billing"


def cfg(checks, tmp_path, sources=None):
    return {"sources": sources or {"t": {"path": "t.csv"}}, "checks": checks}


def test_every_problem_is_reported_at_once(tmp_path):
    bad = cfg([{"type": "nott_null", "table": "t"},
               {"type": "unique", "table": "missing_table", "columns": ["id"]},
               {"type": "range", "table": "t", "column": "x"},
               {"type": "not_null", "table": "t", "columns": "id", "colour": "red"},
               {"type": "foreign_key", "table": "t", "columns": ["a", "b"], "ref_table": "t", "ref_columns": ["a"]},
               {"type": "unique", "table": "t", "columns": ["id"], "severity": "fatal"}], tmp_path)
    with pytest.raises(ConfigError) as e:
        parse(bad, tmp_path)
    text = "\n".join(e.value.problems)
    assert "unknown type 'nott_null'" in text
    assert "'missing_table' is not a defined source" in text
    assert "give 'min', 'max' or both" in text
    assert "unknown option colour" in text and "'columns' must be a list" in text
    assert "same length" in text
    assert "severity must be one of" in text
    assert len(e.value.problems) == 7


def test_a_valid_config_gets_default_names(tmp_path):
    c = parse(cfg([{"type": "unique", "table": "t", "columns": ["id"]}], tmp_path), tmp_path)
    assert c.checks[0].name == "unique: t (id)" and c.checks[0].severity == "error"


def test_a_check_that_cannot_run_is_reported_not_raised(tmp_path):
    (tmp_path / "t.csv").write_text("id,name\n1,a\n2,b\n", encoding="utf-8")
    c = parse(cfg([{"type": "not_null", "table": "t", "columns": ["nme"]},
                   {"type": "unique", "table": "t", "columns": ["id"]}], tmp_path), tmp_path)
    result = run(c)
    assert [r.status for r in result.results] == ["error", "pass"]
    assert "nme" in result.results[0].note
    assert not result.ok()


def test_warnings_only_block_when_asked(tmp_path):
    (tmp_path / "t.csv").write_text("id,name\n1,\n2,b\n", encoding="utf-8")
    c = parse(cfg([{"type": "not_null", "table": "t", "columns": ["name"], "severity": "warn"}], tmp_path), tmp_path)
    result = run(c)
    assert result.ok() and not result.ok(fail_on="warn")


@pytest.fixture(scope="module")
def demo_data():
    subprocess.run([sys.executable, str(DEMO / "make_demo_data.py")], check=True)
    return json.loads((DEMO / "data" / "expected.json").read_text(encoding="utf-8"))


def test_demo_finds_exactly_what_was_planted(demo_data):
    from dqcheck import load
    result = run(load(DEMO / "checks.yml"))
    found = {r.name: r.failing for r in result.results}
    assert found == demo_data
    assert all(r.status != "error" for r in result.results)


def cli(*args):
    return subprocess.run([sys.executable, "-m", "dqcheck", *args], cwd=ROOT, capture_output=True, text=True)


def test_cli_exit_codes(demo_data, tmp_path):
    out = tmp_path / "report"
    p = cli("run", str(DEMO / "checks.yml"), "--out", str(out))
    assert p.returncode == 1 and "12 failed" in p.stdout
    assert (out / "report.md").exists() and (out / "report.html").exists()
    summary = json.loads((out / "results.json").read_text(encoding="utf-8"))["summary"]
    assert summary == {"pass": 4, "fail_error": 12, "fail_warn": 1, "error": 0}

    bad = tmp_path / "bad.yml"
    bad.write_text("sources: {}\nchecks: []\n", encoding="utf-8")
    assert cli("run", str(bad)).returncode == 2

    (tmp_path / "t.csv").write_text("id,name\n1,\n2,b\n", encoding="utf-8")
    warn_only = tmp_path / "warn.yml"
    warn_only.write_text("sources: {t: t.csv}\nchecks:\n  - {type: not_null, table: t, columns: [name], severity: warn}\n",
                         encoding="utf-8")
    assert cli("run", str(warn_only)).returncode == 0
    assert cli("run", str(warn_only), "--fail-on", "warn").returncode == 1
