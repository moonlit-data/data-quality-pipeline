"""Unit tests for each check, with the edge cases spelled out."""
import duckdb
import pytest

from dqcheck.checks import CHECKS, CheckError


@pytest.fixture
def con():
    c = duckdb.connect()
    yield c
    c.close()


def make(con, name, sql_values, columns):
    con.execute(f'CREATE OR REPLACE TABLE "{name}" AS SELECT * FROM (VALUES {sql_values}) AS v({columns})')


def run(con, check_type, **options):
    return CHECKS[check_type](con, options)


# --- not_null ---------------------------------------------------------------------------------------

def test_not_null_counts_null_and_blank_text(con):
    make(con, "t", "(1, 'a'), (2, NULL), (3, ''), (4, '   ')", "id, name")
    assert run(con, "not_null", table="t", columns=["name"]).failing == 3
    assert run(con, "not_null", table="t", columns=["name"], treat_blank_as_null=False).failing == 1


def test_not_null_counts_a_row_once_even_if_several_columns_are_missing(con):
    make(con, "t", "(1, NULL, NULL), (2, 'x', NULL), (3, 'x', 'y')", "id, a, b")
    out = run(con, "not_null", table="t", columns=["a", "b"])
    assert out.failing == 2 and "a: 1, b: 2" in out.note


def test_not_null_on_an_empty_table_passes(con):
    con.execute("CREATE TABLE t (id INTEGER, name VARCHAR)")
    out = run(con, "not_null", table="t", columns=["name"])
    assert (out.failing, out.total) == (0, 0)


def test_not_null_on_numbers_does_not_treat_zero_as_blank(con):
    make(con, "t", "(0), (NULL), (5)", "amount")
    assert run(con, "not_null", table="t", columns=["amount"]).failing == 1


# --- unique -----------------------------------------------------------------------------------------

def test_unique_lists_every_copy_of_a_duplicated_key(con):
    make(con, "t", "(1, 'a'), (1, 'b'), (1, 'c'), (2, 'd')", "id, v")
    out = run(con, "unique", table="t", columns=["id"])
    assert out.failing == 3 and out.note.startswith("1 duplicated")


def test_unique_with_a_composite_key(con):
    make(con, "t", "(1, 'x'), (1, 'y'), (1, 'x')", "a, b")
    assert run(con, "unique", table="t", columns=["a", "b"]).failing == 2


def test_unique_skips_null_keys_and_says_so(con):
    make(con, "t", "(NULL, 1), (NULL, 2), (5, 3)", "id, v")
    out = run(con, "unique", table="t", columns=["id"])
    assert out.failing == 0 and "2 row(s) with a NULL key" in out.note


def test_unique_is_case_sensitive(con):
    make(con, "t", "('A'), ('a')", "code")
    assert run(con, "unique", table="t", columns=["code"]).failing == 0


# --- accepted_values -------------------------------------------------------------------------------

def test_accepted_values_skips_null_and_blank(con):
    make(con, "t", "('US'), ('XX'), (NULL), (''), ('us')", "country")
    assert run(con, "accepted_values", table="t", column="country", values=["US"]).failing == 2


def test_accepted_values_case_insensitive_option(con):
    make(con, "t", "('US'), ('us'), ('Us'), ('GB')", "country")
    assert run(con, "accepted_values", table="t", column="country", values=["US"], case_sensitive=False).failing == 1


def test_accepted_values_with_numbers(con):
    make(con, "t", "(1), (2), (3)", "level")
    assert run(con, "accepted_values", table="t", column="level", values=[1, 2]).failing == 1


def test_accepted_values_escapes_quotes_in_values(con):
    make(con, "t", "('O''Brien'), ('Smith')", "name")
    assert run(con, "accepted_values", table="t", column="name", values=["O'Brien"]).failing == 1


# --- range --------------------------------------------------------------------------------------------

def test_range_bounds_are_inclusive_by_default(con):
    make(con, "t", "(0), (10), (-0.01), (10.01), (NULL)", "x")
    assert run(con, "range", table="t", column="x", min=0, max=10).failing == 2


def test_range_exclusive_bounds(con):
    make(con, "t", "(0), (5), (10)", "x")
    assert run(con, "range", table="t", column="x", min=0, max=10, exclusive_min=True, exclusive_max=True).failing == 2


def test_range_with_only_a_minimum(con):
    make(con, "t", "(-1), (0), (1000000)", "x")
    assert run(con, "range", table="t", column="x", min=0).failing == 1


# --- regex --------------------------------------------------------------------------------------------

def test_regex_matches_the_whole_value_by_default(con):
    make(con, "t", "('abc'), ('abc123'), (NULL), ('')", "code")
    assert run(con, "regex", table="t", column="code", pattern="[a-z]+").failing == 1
    assert run(con, "regex", table="t", column="code", pattern="[a-z]+", full_match=False).failing == 0


def test_regex_pattern_with_a_quote(con):
    make(con, "t", "('it''s'), ('its')", "w")
    assert run(con, "regex", table="t", column="w", pattern="it's").failing == 1


# --- foreign_key ------------------------------------------------------------------------------------

def test_foreign_key_finds_orphans_and_skips_null(con):
    make(con, "parent", "(1), (2), (2)", "id")
    make(con, "child", "(1), (2), (3), (NULL)", "parent_id")
    out = run(con, "foreign_key", table="child", columns=["parent_id"], ref_table="parent", ref_columns=["id"])
    assert out.failing == 1   # only 3; NULL skipped; the duplicate 2 in parent does not matter


def test_foreign_key_with_a_composite_key(con):
    make(con, "parent", "(1, 'a'), (1, 'b')", "id, part")
    make(con, "child", "(1, 'a'), (1, 'c')", "id, part")
    assert run(con, "foreign_key", table="child", columns=["id", "part"], ref_table="parent",
               ref_columns=["id", "part"]).failing == 1


# --- reconcile --------------------------------------------------------------------------------------

def test_reconcile_tolerance_boundary(con):
    make(con, "inv", "(1, 10.00), (2, 10.01), (3, 10.02)", "id, total")
    make(con, "line", "(1, 10.00), (2, 10.00), (3, 10.00)", "id, amount")
    out = run(con, "reconcile", parent="inv", parent_key=["id"], parent_amount="total", child="line",
              child_key=["id"], child_amount="amount", tolerance=0.01)
    assert out.failing == 1   # a 0.01 difference passes, 0.02 fails


def test_reconcile_parent_without_children_is_compared_with_zero(con):
    make(con, "inv", "(1, 0.00), (2, 5.00)", "id, total")
    con.execute("CREATE TABLE line (id INTEGER, amount DECIMAL(10,2))")
    out = run(con, "reconcile", parent="inv", parent_key=["id"], parent_amount="total", child="line",
              child_key=["id"], child_amount="amount", tolerance=0)
    assert out.failing == 1


def test_reconcile_ignores_floating_point_noise(con):
    make(con, "inv", "(1, 0.3::DOUBLE)", "id, total")
    make(con, "line", "(1, 0.1::DOUBLE), (1, 0.2::DOUBLE)", "id, amount")
    assert run(con, "reconcile", parent="inv", parent_key=["id"], parent_amount="total", child="line",
               child_key=["id"], child_amount="amount", tolerance=0).failing == 0


def test_reconcile_with_an_expression(con):
    make(con, "inv", "(1, 30.0)", "id, total")
    make(con, "line", "(1, 2, 10.0), (1, 1, 10.0)", "id, qty, price")
    assert run(con, "reconcile", parent="inv", parent_key=["id"], parent_amount="total", child="line",
               child_key=["id"], child_amount="qty * price").failing == 0


# --- duplicate_transactions -------------------------------------------------------------------------

def test_duplicate_window_is_inclusive(con):
    make(con, "p", """('c1', 10, TIMESTAMP '2026-01-01 10:00:00'), ('c1', 10, TIMESTAMP '2026-01-01 10:05:00'),
                      ('c2', 10, TIMESTAMP '2026-01-01 10:00:00'), ('c2', 10, TIMESTAMP '2026-01-01 10:05:01')""",
         "customer, amount, ts")
    out = run(con, "duplicate_transactions", table="p", keys=["customer", "amount"], timestamp="ts", window_minutes=5)
    assert out.failing == 1   # exactly 5:00 apart counts, 5:01 does not


def test_duplicate_chain_flags_each_later_copy(con):
    make(con, "p", """('c1', 10, TIMESTAMP '2026-01-01 10:00'), ('c1', 10, TIMESTAMP '2026-01-01 10:03'),
                      ('c1', 10, TIMESTAMP '2026-01-01 10:06'), ('c1', 11, TIMESTAMP '2026-01-01 10:07')""",
         "customer, amount, ts")
    assert run(con, "duplicate_transactions", table="p", keys=["customer", "amount"], timestamp="ts",
               window_minutes=5).failing == 2


def test_duplicate_skips_rows_with_null_keys(con):
    make(con, "p", """(NULL, 10, TIMESTAMP '2026-01-01 10:00'), (NULL, 10, TIMESTAMP '2026-01-01 10:01')""",
         "customer, amount, ts")
    assert run(con, "duplicate_transactions", table="p", keys=["customer", "amount"], timestamp="ts",
               window_minutes=5).failing == 0


# --- outliers ---------------------------------------------------------------------------------------

def test_outlier_is_found(con):
    values = ", ".join(f"({v})" for v in [100, 102, 98, 101, 99, 103, 97, 100, 101, 99, 5000])
    make(con, "t", values, "amount")
    out = run(con, "outliers", table="t", column="amount")
    assert out.failing == 1


def test_outliers_when_mad_is_zero_falls_back_to_mean_deviation(con):
    make(con, "t", ", ".join(["(10)"] * 20 + ["(1000)"]), "amount")
    assert run(con, "outliers", table="t", column="amount").failing == 1


def test_outliers_when_all_values_are_equal_flags_nothing(con):
    make(con, "t", ", ".join(["(10)"] * 20), "amount")
    assert run(con, "outliers", table="t", column="amount").failing == 0


def test_outliers_skip_small_groups_and_compare_within_groups(con):
    big = [("'a'", v) for v in [10, 11, 9, 10, 12, 8, 10, 11, 9, 10, 500]]      # 500 is extreme for a
    normal_b = [("'b'", v) for v in [490, 510, 500, 505, 495, 500, 498, 502, 499, 501]]  # 500 is normal for b
    small = [("'c'", v) for v in [1, 1000]]                                        # too few rows to judge
    make(con, "t", ", ".join(f"({g}, {v})" for g, v in big + normal_b + small), "grp, amount")
    out = run(con, "outliers", table="t", column="amount", group_by=["grp"])
    assert out.failing == 1 and "1 group(s) under 10 rows skipped" in out.note


# --- row_count, freshness, custom_sql ------------------------------------------------------------------

def test_row_count_limits(con):
    make(con, "t", "(1), (2), (3)", "x")
    assert run(con, "row_count", table="t", min=3, max=3).failing == 0
    assert run(con, "row_count", table="t", min=4).failing == 1
    assert run(con, "row_count", table="t", max=2).failing == 1


def test_freshness(con):
    make(con, "t", "(DATE '2026-10-20'), (DATE '2026-10-25')", "d")
    assert run(con, "freshness", table="t", column="d", max_age_days=6, as_of="2026-10-31").failing == 0
    assert run(con, "freshness", table="t", column="d", max_age_days=5, as_of="2026-10-31").failing == 1


def test_freshness_of_an_empty_table_fails(con):
    con.execute("CREATE TABLE t (d DATE)")
    out = run(con, "freshness", table="t", column="d", max_age_days=5, as_of="2026-10-31")
    assert out.failing == 1 and "empty" in out.note


def test_custom_sql_counts_returned_rows(con):
    make(con, "t", "(1), (2), (3)", "x")
    assert run(con, "custom_sql", sql="SELECT * FROM t WHERE x > 1;").failing == 2


# --- errors and odd names -----------------------------------------------------------------------------

def test_missing_column_gives_a_clear_error(con):
    make(con, "t", "(1)", "id")
    with pytest.raises(CheckError, match="emial.*not found.*columns: id"):
        run(con, "not_null", table="t", columns=["emial"])


def test_column_names_with_spaces_and_quotes(con):
    con.execute('CREATE TABLE "my table" ("first name" VARCHAR, "it""s" INTEGER)')
    con.execute("""INSERT INTO "my table" VALUES (NULL, 1), ('Ann', 1)""")
    assert run(con, "not_null", table="my table", columns=["first name"]).failing == 1
    assert run(con, "unique", table="my table", columns=['it"s']).failing == 2
