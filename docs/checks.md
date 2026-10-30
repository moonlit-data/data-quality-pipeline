# Check reference

Every check has `type`, optional `name` (shown in the report), optional `severity` (`error`, the
default, or `warn`) and optional `description`. Each check is turned into one SQL query that returns
the failing rows; the report shows the first five and the query itself.

| Type | Options | Fails when | Edge cases |
|---|---|---|---|
| `not_null` | `table`, `columns`, `treat_blank_as_null` (default true) | any listed column is NULL; for text also empty or only spaces | a row missing several columns counts once; the note gives counts per column; numbers: 0 is a value, not blank |
| `unique` | `table`, `columns` (one or more = composite key) | the key appears more than once; **every copy** is listed | rows with a NULL in the key are not checked (the note says how many) - that is a `not_null` question; comparison is case-sensitive |
| `accepted_values` | `table`, `column`, `values`, `case_sensitive` (default true) | the value is not in the list | NULL and blank text are not checked; quotes in values are escaped |
| `range` | `table`, `column`, `min` and/or `max`, `exclusive_min`, `exclusive_max` | the value is below `min` or above `max` | bounds are inclusive unless made exclusive; NULL is not checked |
| `regex` | `table`, `column`, `pattern`, `full_match` (default true) | the text does not match | the **whole** value must match unless `full_match: false`; NULL and blank text are not checked |
| `foreign_key` | `table`, `columns`, `ref_table`, `ref_columns` | the key has no match in the referenced table | child rows with a NULL key are not checked; duplicates in the referenced table do not multiply rows (`NOT EXISTS`) |
| `reconcile` | `parent`, `parent_key`, `parent_amount`, `child`, `child_key`, `child_amount`, `tolerance` (default 0.01) | parent amount and the sum of its children differ by **more than** the tolerance | a difference equal to the tolerance passes; a parent with no children is compared with 0; sums are compared as doubles with a 1e-9 margin, so 0.1 + 0.2 equals 0.3; `child_amount` may be an expression |
| `duplicate_transactions` | `table`, `keys`, `timestamp`, `window_minutes` | a row repeats the keys of the previous row within the window | the window is inclusive (exactly 5:00 apart is a duplicate, 5:01 is not); in a run of copies every later copy is listed, the first is treated as the original; rows with NULL keys or time are not checked |
| `outliers` | `table`, `column`, `group_by`, `threshold` (default 3.5), `min_group_size` (default 10) | robust z-score above the threshold: 0.6745 x (value - median) / MAD | if MAD is 0, uses (value - median) / (1.2533 x mean absolute deviation); if that is 0 too, all values are equal and nothing is flagged; groups smaller than `min_group_size` are skipped and counted in the note; NULL ignored |
| `row_count` | `table`, `min` and/or `max` | the row count is outside the limits | |
| `freshness` | `table`, `column`, `max_age_days`, `as_of` (default today) | the newest value is older than `max_age_days` before `as_of` | an empty table fails |
| `custom_sql` | `sql`, `table` (only for the "checked" count) | the query returns any row | any SQL DuckDB can run; a trailing `;` is fine |

## Why median and MAD for outliers

A mean and standard deviation are pulled towards the very values they are meant to catch: one payment of
30,000 among payments of 200 raises the standard deviation so much that it can hide itself. The median and
the median absolute deviation (MAD) barely move, so the score stays honest. 3.5 is the cut-off suggested by
Iglewicz and Hoaglin; for skewed money amounts a higher threshold, or `group_by` (for example by product),
is usually better. The demo uses 8.

## Configuration errors

The whole file is checked before any data is read, and every problem is listed at once: unknown check
types, missing or misspelled options, a table that is not a defined source, `columns`/`ref_columns` of
different lengths, an invalid severity. A check that fails at run time (for example a misspelled column)
is reported with status ERROR and the list of real columns; the other checks still run.

## Exit codes

| Code | Meaning |
|---|---|
| 0 | every `error`-severity check passed (warnings allowed unless `--fail-on warn`) |
| 1 | at least one check failed, or could not run |
| 2 | the configuration is invalid |
