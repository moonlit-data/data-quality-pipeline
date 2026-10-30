# Billing data quality

Run 2026-10-29 12:48:42. 17 checks: 4 passed, 12 failed, 1 warnings, 0 could not run.

Sources: `customers` (1,004 rows), `invoices` (5,000 rows), `invoice_lines` (15,015 rows), `payments` (4,764 rows)

| Status | Check | Type | Failing | Checked | % |
|---|---|---|---:|---:|---:|
| ✕ FAIL | customer_id is unique | `unique` | 8 | 1,004 | 0.8% |
| ✕ FAIL | email address is well formed | `regex` | 7 | 1,004 | 0.7% |
| ✕ FAIL | country is a supported ISO code | `accepted_values` | 5 | 1,004 | 0.5% |
| ✕ FAIL | invoice customer exists | `foreign_key` | 10 | 5,000 | 0.2% |
| ✕ FAIL | invoice total is not negative | `range` | 8 | 5,000 | 0.16% |
| ✕ FAIL | invoice total equals the sum of its lines | `reconcile` | 28 | 5,000 | 0.56% |
| ✕ FAIL | invoice line belongs to an invoice | `foreign_key` | 15 | 15,015 | 0.1% |
| ✕ FAIL | line quantity is at least 1 | `range` | 6 | 15,015 | 0.04% |
| ✕ FAIL | payment belongs to an invoice | `foreign_key` | 10 | 4,764 | 0.21% |
| ✕ FAIL | no double-charged payments | `duplicate_transactions` | 12 | 4,764 | 0.25% |
| ✕ FAIL | payment amount is not extreme | `outliers` | 6 | 4,764 | 0.13% |
| ✕ FAIL | no invoice is paid more than its total | `custom_sql` | 18 | 5,000 | 0.36% |
| ! WARN | customers have an email | `not_null` | 25 | 1,004 | 2.49% |
| ✓ PASS | invoice_id is unique | `unique` | 0 | 5,000 | 0.0% |
| ✓ PASS | payment_id is unique | `unique` | 0 | 4,764 | 0.0% |
| ✓ PASS | payments table is not empty | `row_count` | no | 4,764 |  |
| ✓ PASS | payments are recent | `freshness` | no | 4,764 |  |

## Details

### ✕ customer_id is unique

4 duplicated key value(s)

| customer_id | email | country | created_at | dup_count |
|---|---|---|---|---|
| C0112 | billing112@example1.com | CA | 2024-03-01 | 2 |
| C0112 | accounts111@example.org | CA | 2024-03-01 | 2 |
| C0595 | accounts594@example.org | FR | 2023-07-30 | 2 |
| C0595 | billing595@example3.com | FR | 2023-07-30 | 2 |
| C0666 | billing666@example0.com | DE | 2024-05-18 | 2 |

First 5 of 8.

<details><summary>SQL</summary>

```sql
SELECT * FROM (SELECT *, COUNT(*) OVER (PARTITION BY "customer_id") AS dup_count FROM "customers" WHERE "customer_id" IS NOT NULL) AS k WHERE dup_count > 1 ORDER BY "customer_id"
```

</details>

### ✕ email address is well formed

| customer_id | email | country | created_at |
|---|---|---|---|
| C0113 | billing.example.com | US | 2024-08-25 |
| C0170 | billing@example .com | CA | 2024-04-30 |
| C0238 | @example.com | DE | 2024-06-06 |
| C0511 | billing@@example.com | AU | 2024-04-04 |
| C0717 | billing@example | CA | 2025-07-31 |

First 5 of 7.

<details><summary>SQL</summary>

```sql
SELECT * FROM "customers" WHERE NULLIF(trim(CAST("email" AS VARCHAR)), '') IS NOT NULL AND NOT regexp_full_match(CAST("email" AS VARCHAR), '[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}')
```

</details>

### ✕ country is a supported ISO code

| customer_id | email | country | created_at |
|---|---|---|---|
| C0083 | billing83@example9.com | Germany | 2024-08-08 |
| C0652 | billing652@example23.com | USA | 2023-07-24 |
| C0714 | billing714@example11.com | U.S. | 2024-08-17 |
| C0786 | billing786@example9.com | uk | 2024-07-30 |
| C0807 | billing807@example30.com | XX | 2023-06-28 |

First 5 of 5.

<details><summary>SQL</summary>

```sql
SELECT * FROM "customers" WHERE NULLIF(trim(CAST("country" AS VARCHAR)), '') IS NOT NULL AND "country" NOT IN ('US', 'CA', 'GB', 'DE', 'FR', 'AU')
```

</details>

### ✕ invoice customer exists

| invoice_id | customer_id | invoice_date | total | currency |
|---|---|---|---|---|
| INV01122 | C9901 | 2026-07-25 | 219.21 | USD |
| INV01258 | C9540 | 2026-09-07 | 216.91 | USD |
| INV01416 | C9121 | 2026-02-17 | 315.96 | USD |
| INV01869 | C9186 | 2025-10-01 | 153.45 | USD |
| INV02658 | C9729 | 2025-12-02 | 231.91 | USD |

First 5 of 10.

<details><summary>SQL</summary>

```sql
SELECT c.* FROM "invoices" AS c WHERE c."customer_id" IS NOT NULL AND NOT EXISTS (SELECT 1 FROM "customers" AS p WHERE p."customer_id" = c."customer_id")
```

</details>

### ✕ invoice total is not negative

| invoice_id | customer_id | invoice_date | total | currency |
|---|---|---|---|---|
| INV00049 | C0786 | 2026-07-31 | -188.38 | USD |
| INV00173 | C0230 | 2026-09-16 | -223.77 | USD |
| INV00730 | C0773 | 2026-02-28 | -194.28 | USD |
| INV00861 | C0540 | 2026-09-28 | -274.78 | USD |
| INV00970 | C0176 | 2025-11-15 | -307.39 | USD |

First 5 of 8.

<details><summary>SQL</summary>

```sql
SELECT * FROM "invoices" WHERE "total" IS NOT NULL AND ("total" < 0)
```

</details>

### ✕ invoice total equals the sum of its lines

| invoice_id | customer_id | invoice_date | total | currency | child_total | difference |
|---|---|---|---|---|---|---|
| INV00035 | C0105 | 2025-11-12 | 129.94 | USD | 124.94 | 5.0 |
| INV02972 | C0179 | 2026-09-24 | 210.38 | USD | 205.38 | 5.0 |
| INV02561 | C0910 | 2026-02-02 | 208.87 | USD | 208.37 | 0.5 |
| INV00861 | C0540 | 2026-09-28 | -274.78 | USD | 274.78 | -549.56 |
| INV04917 | C0639 | 2026-01-28 | 373.9 | USD | 273.91 | 99.99 |

First 5 of 28.

<details><summary>SQL</summary>

```sql
WITH ch AS (SELECT "invoice_id" AS _k0, SUM(quantity * unit_price) AS _child_total FROM "invoice_lines" GROUP BY ALL) SELECT p.*, COALESCE(ch._child_total, 0) AS child_total, p."total" - COALESCE(ch._child_total, 0) AS difference FROM "invoices" AS p LEFT JOIN ch ON ch._k0 = p."invoice_id" WHERE p."total" IS NOT NULL AND ABS(CAST(p."total" AS DOUBLE) - CAST(COALESCE(ch._child_total, 0) AS DOUBLE)) > 0.01 + 1e-9
```

</details>

### ✕ invoice line belongs to an invoice

| line_id | invoice_id | product | quantity | unit_price |
|---|---|---|---|---|
| L015001 | INV90000 | Basic plan | 1 | 29.0 |
| L015002 | INV90001 | Basic plan | 1 | 29.0 |
| L015003 | INV90002 | Basic plan | 1 | 29.0 |
| L015004 | INV90003 | Basic plan | 1 | 29.0 |
| L015005 | INV90004 | Basic plan | 1 | 29.0 |

First 5 of 15.

<details><summary>SQL</summary>

```sql
SELECT c.* FROM "invoice_lines" AS c WHERE c."invoice_id" IS NOT NULL AND NOT EXISTS (SELECT 1 FROM "invoices" AS p WHERE p."invoice_id" = c."invoice_id")
```

</details>

### ✕ line quantity is at least 1

| line_id | invoice_id | product | quantity | unit_price |
|---|---|---|---|---|
| L003589 | INV01197 | Basic plan | 0 | 31.72 |
| L003928 | INV01310 | Basic plan | 0 | 53.35 |
| L005032 | INV01678 | Basic plan | 0 | 48.18 |
| L007153 | INV02385 | Support hours | 0 | 38.14 |
| L010369 | INV03457 | Pro plan | 0 | 23.62 |

First 5 of 6.

<details><summary>SQL</summary>

```sql
SELECT * FROM "invoice_lines" WHERE "quantity" IS NOT NULL AND ("quantity" < 1)
```

</details>

### ✕ payment belongs to an invoice

| payment_id | invoice_id | customer_id | paid_at | amount | method |
|---|---|---|---|---|---|
| P004755 | INV80000 | C0001 | 2025-10-01 10:00:00 | 100.0 | ach |
| P004756 | INV80001 | C0001 | 2025-10-31 10:00:00 | 107.13 | ach |
| P004757 | INV80002 | C0001 | 2025-11-30 10:00:00 | 114.26 | ach |
| P004758 | INV80003 | C0001 | 2025-12-30 10:00:00 | 121.39 | ach |
| P004759 | INV80004 | C0001 | 2026-01-29 10:00:00 | 128.52 | ach |

First 5 of 10.

<details><summary>SQL</summary>

```sql
SELECT c.* FROM "payments" AS c WHERE c."invoice_id" IS NOT NULL AND NOT EXISTS (SELECT 1 FROM "invoices" AS p WHERE p."invoice_id" = c."invoice_id")
```

</details>

### ✕ no double-charged payments

| payment_id | invoice_id | customer_id | paid_at | amount | method | minutes_after_previous |
|---|---|---|---|---|---|---|
| P004745 | INV02083 | C0625 | 2026-05-08 10:57:00 | 175.1 | card | 3.0 |
| P004754 | INV02145 | C0034 | 2025-12-24 13:12:00 | 263.88 | card | 2.0 |
| P004744 | INV03163 | C0084 | 2025-11-10 17:58:00 | 292.54 | card | 4.0 |
| P004753 | INV02646 | C0510 | 2026-04-01 18:43:00 | 206.55 | card | 4.0 |
| P004751 | INV00559 | C0568 | 2026-08-27 00:16:00 | 177.9 | card | 4.0 |

First 5 of 12.

<details><summary>SQL</summary>

```sql
SELECT * EXCLUDE (_prev_ts), date_diff('second', _prev_ts, "paid_at") / 60.0 AS minutes_after_previous FROM (SELECT *, LAG("paid_at") OVER (PARTITION BY "customer_id", "amount" ORDER BY "paid_at") AS _prev_ts FROM "payments" WHERE "customer_id" IS NOT NULL AND "amount" IS NOT NULL AND "paid_at" IS NOT NULL) AS x WHERE _prev_ts IS NOT NULL AND date_diff('second', _prev_ts, "paid_at") <= 300.0
```

</details>

### ✕ payment amount is not extreme

threshold |z| > 8.0

| payment_id | invoice_id | customer_id | paid_at | amount | method | group_median | robust_z |
|---|---|---|---|---|---|---|---|
| P000508 | INV00540 | C0118 | 2026-04-14 19:33:00 | 29044.0 | card | 234.995 | 388.1289 |
| P000702 | INV00746 | C0797 | 2026-04-23 15:51:00 | 28135.0 | card | 234.995 | 375.8824 |
| P000330 | INV00356 | C0151 | 2026-03-28 12:47:00 | 25605.0 | card | 234.995 | 341.797 |
| P004198 | INV04423 | C0491 | 2026-04-22 19:43:00 | 25329.0 | card | 234.995 | 338.0786 |
| P000485 | INV00517 | C0141 | 2026-01-28 15:10:00 | 22877.0 | card | 234.995 | 305.0441 |

First 5 of 6.

<details><summary>SQL</summary>

```sql
WITH base AS (SELECT *, CAST("amount" AS DOUBLE) AS _x, 'all' AS _grp FROM "payments" WHERE "amount" IS NOT NULL), med AS (SELECT _grp, median(_x) AS _med, COUNT(*) AS _n FROM base GROUP BY ALL), dev AS (SELECT _grp, median(abs(b._x - m._med)) AS _mad, avg(abs(b._x - m._med)) AS _meanad FROM base AS b JOIN med AS m USING (_grp) GROUP BY ALL), scored AS (SELECT b.*, m._med AS group_median, m._n AS _n, CASE WHEN d._mad > 0 THEN 0.6745 * (b._x - m._med) / d._mad WHEN d._meanad > 0 THEN (b._x - m._med) / (1.2533 * d._meanad) ELSE 0 END AS robust_z FROM base AS b JOIN med AS m USING (_grp) JOIN dev AS d USING (_grp)) SELECT * EXCLUDE (_x, _n, _grp) FROM scored WHERE _n >= 10 AND abs(robust_z) > 8.0 ORDER BY abs(robust_z) DESC
```

</details>

### ✕ no invoice is paid more than its total

| invoice_id | total | paid | overpaid |
|---|---|---|---|
| INV02145 | 263.88 | 527.76 | 263.88 |
| INV00249 | 221.08 | 442.16 | 221.08 |
| INV02083 | 175.1 | 350.2 | 175.1 |
| INV02551 | 114.02 | 228.04 | 114.02 |
| INV04423 | 253.29 | 25329.0 | 25075.71 |

First 5 of 18.

<details><summary>SQL</summary>

```sql
SELECT i.invoice_id, i.total, SUM(p.amount) AS paid, SUM(p.amount) - i.total AS overpaid
FROM invoices AS i
JOIN payments AS p USING (invoice_id)
GROUP BY i.invoice_id, i.total
HAVING SUM(p.amount) > i.total + 0.01
```

</details>

### ! customers have an email

missing per column - email: 25

| customer_id | email | country | created_at |
|---|---|---|---|
| C0005 |   | GB | 2024-01-14 |
| C0056 |   | FR | 2023-06-08 |
| C0098 |   | AU | 2025-07-08 |
| C0163 |  | FR | 2023-12-17 |
| C0189 |   | US | 2024-03-11 |

First 5 of 25.

<details><summary>SQL</summary>

```sql
SELECT * FROM "customers" WHERE ("email" IS NULL OR trim("email") = '')
```

</details>

