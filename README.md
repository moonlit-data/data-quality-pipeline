# Automated Data Quality Pipeline

**Python · SQL (DuckDB) · automated testing**

`dqcheck` runs data quality checks on CSV or Parquet files from a short YAML file and writes a report
(Markdown, HTML, JSON). It finds duplicate transactions, missing fields, values outside allowed ranges or
lists, records with no parent, amounts that do not add up across tables and extreme values, and returns an
exit code a scheduled job or CI pipeline can stop on.

```
$ python -m dqcheck run examples/billing/checks.yml
17 checks: 4 passed, 12 failed, 1 warnings, 0 could not run
  FAIL  customer_id is unique: 8
  WARN  customers have an email: 25
  FAIL  invoice total equals the sum of its lines: 28
  FAIL  no double-charged payments: 12
  FAIL  payment amount is not extreme: 6
  ...
report: examples/billing/report/report.md
```

Example report: [examples/billing/report/report.md](examples/billing/report/report.md)
(also as [HTML](examples/billing/report/report.html) and [JSON](examples/billing/report/results.json)).

## How do we know it finds the right things?

The demo data ([`examples/billing/make_demo_data.py`](examples/billing/make_demo_data.py)) is a clean
billing system - 1,000 customers, 5,000 invoices, 15,000 invoice lines, about 4,740 payments - with a known
number of problems planted on purpose, recorded in [`expected.json`](examples/billing/data/expected.json):

| Planted | Check that should catch it | Found |
|---|---|---:|
| 4 customer IDs entered twice | `unique` (both copies listed) | 8 |
| 15 blank and 10 NULL emails | `not_null` (blank counts as missing) | 25 |
| 7 malformed emails | `regex` (blank ones are not counted again) | 7 |
| 5 country codes like `USA`, `uk` | `accepted_values` | 5 |
| 10 invoices for customers that do not exist | `foreign_key` | 10 |
| 8 negative invoice totals | `range` | 8 |
| 20 totals changed after the fact + the 8 negative ones | `reconcile` with the invoice lines | 28 |
| 15 invoice lines for invoices that do not exist | `foreign_key` | 15 |
| 6 lines with quantity 0 | `range` | 6 |
| 10 payments for invoices that do not exist | `foreign_key` | 10 |
| 12 payments taken twice within 4 minutes | `duplicate_transactions` | 12 |
| 6 payments with an extra "00" typed in | `outliers` (robust z-score) | 6 |
| the 12 double charges + the 6 typos overpay their invoice | `custom_sql` | 18 |

The clean part is built so that no check can fire on it by chance (for example, every untouched invoice
equals the exact sum of its lines), and the test suite asserts that every check finds exactly the planted
number - no more, no less.

## Checks

| Type | Finds |
|---|---|
| `not_null` | missing values (NULL, and for text also empty or blank) |
| `unique` | duplicate keys, single or composite |
| `accepted_values` | values outside an allowed list |
| `range` | numbers or dates outside limits |
| `regex` | badly formatted text (emails, IDs, codes) |
| `foreign_key` | records whose parent does not exist |
| `reconcile` | parent totals that do not equal the sum of their children (invoice vs lines, order vs payments) |
| `duplicate_transactions` | the same transaction repeated within a time window |
| `outliers` | extreme values, by a robust z-score (median and MAD), optionally within groups |
| `row_count`, `freshness` | a table that is empty, too big or not updated |
| `custom_sql` | any rule you can write as a query |

Every edge case is decided and written down - NULL keys, blank text, inclusive or exclusive bounds,
the tolerance boundary, the duplicate window boundary, MAD = 0, small groups - in
[docs/checks.md](docs/checks.md).

A check looks like this:

```yaml
- name: no double-charged payments
  type: duplicate_transactions
  table: payments
  keys: [customer_id, amount]
  timestamp: paid_at
  window_minutes: 5
```

## Design

```
checks.yml --> config.py: validate everything first, list every problem at once
           --> runner.py: load CSV/Parquet into DuckDB with declared types
           --> checks.py: one SQL query per check that returns the failing rows
           --> report.py: Markdown + HTML + JSON with a sample of failing rows and the query
           --> exit code 0 / 1 / 2 for schedulers and CI
```

- Each finding comes with the SQL that produced it, so anyone can rerun it by hand.
- A check that cannot run (a misspelled column) is reported as ERROR with the real column names; the
  other checks still run.
- Identifiers are quoted and values escaped, so tables and columns with spaces or quotes work.
- `--fail-on warn` makes warnings block too; by default only `error` checks do.

## Tests

`python -m pytest` - 42 tests:

- **Unit and boundary tests for every check** ([`tests/test_checks.py`](tests/test_checks.py)): NULL and
  blank handling, composite keys, case sensitivity, inclusive and exclusive bounds, a difference exactly
  equal to the tolerance, 0.1 + 0.2 = 0.3, a duplicate exactly at the window edge, MAD = 0, groups too
  small to judge, an empty table, column names with spaces and quotes, a misspelled column.
- **Configuration and command line** ([`tests/test_config_and_cli.py`](tests/test_config_and_cli.py)):
  seven different mistakes in one file are all reported; exit codes 0, 1 and 2; warnings only block
  with `--fail-on warn`.
- **End to end:** the demo finds exactly the planted problems.

## Run it

Python 3.10+.

```
pip install -r requirements.txt
python examples/billing/make_demo_data.py
python -m dqcheck run examples/billing/checks.yml
python -m pytest
```

To check your own files, copy [`examples/billing/checks.yml`](examples/billing/checks.yml), point the
sources at your files and adjust the checks.

## Limitations

- Everything is loaded into an in-process DuckDB database: fine for files up to a few GB on one machine,
  not a replacement for a warehouse-native tool.
- Configuration files are trusted: `child_amount` expressions and `custom_sql` are run as SQL.
- Outlier detection assumes most values are normal; if a large share of a group is wrong, use rules
  (`range`, `accepted_values`) instead.
