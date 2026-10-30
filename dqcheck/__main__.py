"""Command line:  python -m dqcheck run CONFIG.yml [--out DIR] [--fail-on error|warn]

Exit code 0 when nothing blocks, 1 when a check fails (or warns, with --fail-on warn) or cannot run,
2 when the configuration itself is invalid. Use it as a gate in a scheduled job or CI.
"""
import argparse
import pathlib
import sys

from . import config as config_mod
from . import report
from .runner import run


def main(argv=None):
    p = argparse.ArgumentParser(prog="dqcheck", description="Run data quality checks and write a report.")
    sub = p.add_subparsers(dest="command", required=True)
    r = sub.add_parser("run", help="run the checks in a configuration file")
    r.add_argument("config")
    r.add_argument("--out", help="report folder (default: report/ next to the config)")
    r.add_argument("--fail-on", choices=["error", "warn"], default="error")
    args = p.parse_args(argv)

    try:
        cfg = config_mod.load(args.config)
    except config_mod.ConfigError as e:
        print(e, file=sys.stderr)
        return 2
    result = run(cfg)
    out = pathlib.Path(args.out) if args.out else pathlib.Path(args.config).parent / "report"
    paths = report.write(result, out)
    print(report.summary_line(result))
    for res in result.results:
        k = report.kind(res)
        detail = res.note if (res.status == "error" or res.unit == "table") else report.fmt_count(res)
        print(f"  {report.LABEL[k]:<5} {res.name}: {detail}")
    print(f"report: {paths['markdown']}")
    return 0 if result.ok(args.fail_on) else 1


if __name__ == "__main__":
    sys.exit(main())
