"""Make the demo billing data: clean records plus a known number of planted problems.

Usage:  python examples/billing/make_demo_data.py
Output: examples/billing/data/{customers,invoices,invoice_lines,payments}.csv
        examples/billing/data/expected.json  - how many failures each check should find

The clean part is built so that none of the checks can fire on it by chance (for example, invoice totals
are always the exact sum of their lines). Every planted problem is listed in expected.json, which the
tests compare with what the checks report.
"""
import csv
import datetime as dt
import json
import pathlib
import random

OUT = pathlib.Path(__file__).resolve().parent / "data"
SEED = 7
COUNTRIES = ["US", "CA", "GB", "DE", "FR", "AU"]
PRODUCTS = ["Basic plan", "Pro plan", "Seat add-on", "Storage add-on", "Support hours"]
START = dt.datetime(2025, 10, 1)


def money(x):
    return f"{x:.2f}"


def main():
    rng = random.Random(SEED)
    expected = {}

    # customers -----------------------------------------------------------------------------------
    customers = []
    for i in range(1, 1001):
        cid = f"C{i:04d}"
        customers.append({"customer_id": cid, "email": f"billing{i}@example{i % 37}.com",
                          "country": rng.choice(COUNTRIES), "created_at": (START - dt.timedelta(days=rng.randint(30, 900))).date()})
    picks = rng.sample(range(1000), 25 + 7 + 5)
    for k in picks[:15]:
        customers[k]["email"] = " "                      # blank (a space): missing
    for k in picks[15:25]:
        customers[k]["email"] = None                     # NULL: missing
    expected["customers have an email"] = 25
    bad_emails = ["billing at example.com", "billing@example", "@example.com", "billing@@example.com",
                  "billing@example .com", "billing.example.com", "billing@example.c"]
    for k, e in zip(picks[25:32], bad_emails):
        customers[k]["email"] = e
    expected["email address is well formed"] = 7
    for k, c in zip(picks[32:37], ["USA", "uk", "Germany", "XX", "U.S."]):
        customers[k]["country"] = c
    expected["country is a supported ISO code"] = 5
    untouched = [k for k in range(1000) if k not in set(picks)]
    for k in rng.sample(untouched, 4):                   # the same ID entered twice
        dup = dict(customers[k])
        dup["email"] = f"accounts{k}@example.org"
        customers.append(dup)
    expected["customer_id is unique"] = 8                # both copies of each of the 4 IDs

    # invoices and lines --------------------------------------------------------------------------
    invoices, lines, payments = [], [], []
    line_no = pay_no = 0
    for i in range(1, 5001):
        inv_id = f"INV{i:05d}"
        cust = customers[rng.randrange(1000)]["customer_id"]
        day = START + dt.timedelta(days=rng.randint(0, 364), hours=rng.randint(8, 18), minutes=rng.randint(0, 59))
        total = 0.0
        for _ in range(3):
            line_no += 1
            qty, price = rng.randint(1, 3), round(rng.uniform(20, 60), 2)
            lines.append({"line_id": f"L{line_no:06d}", "invoice_id": inv_id, "product": rng.choice(PRODUCTS),
                          "quantity": qty, "unit_price": money(price)})
            total += qty * price
        invoices.append({"invoice_id": inv_id, "customer_id": cust, "invoice_date": day.date(),
                         "total": money(total), "currency": "USD", "_ts": day})

    k_unknown_customer, k_negative, k_mismatch, k_unpaid = (lambda s: (s[:10], s[10:18], s[18:38], s[38:288]))(
        rng.sample(range(5000), 288))
    special = set(k_unknown_customer) | set(k_negative) | set(k_mismatch) | set(k_unpaid)
    # zero quantities on lines of ordinary invoices, keeping each invoice equal to its lines
    for k in rng.sample([i for i in range(5000) if i not in special], 6):
        lines[3 * k]["quantity"] = 0
        invoices[k]["total"] = money(sum(float(l["unit_price"]) * l["quantity"] for l in lines[3 * k:3 * k + 3]))
    expected["line quantity is at least 1"] = 6
    for k in k_unknown_customer:
        invoices[k]["customer_id"] = f"C9{rng.randint(100, 999)}"
    expected["invoice customer exists"] = 10
    for k in k_negative:
        invoices[k]["total"] = money(-float(invoices[k]["total"]))
    expected["invoice total is not negative"] = 8
    for k in k_mismatch:
        invoices[k]["total"] = money(float(invoices[k]["total"]) + rng.choice([5, 12.5, 40, 0.5, 99.99]))
    expected["invoice total equals the sum of its lines"] = 20 + 8     # negative totals also disagree

    for j in range(15):
        line_no += 1
        lines.append({"line_id": f"L{line_no:06d}", "invoice_id": f"INV9{j:04d}", "product": "Basic plan",
                      "quantity": 1, "unit_price": "29.00"})
    expected["invoice line belongs to an invoice"] = 15

    # payments: one per invoice, except negative and unpaid ones -----------------------------------
    for k, inv in enumerate(invoices):
        if k in k_negative or k in k_unpaid:
            continue
        pay_no += 1
        paid_at = inv["_ts"] + dt.timedelta(days=rng.randint(0, 20), minutes=rng.randint(0, 600))
        if k in k_mismatch:     # the customer paid what the lines add up to
            amount = sum(float(l["unit_price"]) * l["quantity"] for l in lines[3 * k:3 * k + 3])
        else:
            amount = float(inv["total"])
        payments.append({"payment_id": f"P{pay_no:06d}", "invoice_id": inv["invoice_id"], "customer_id": inv["customer_id"],
                         "paid_at": paid_at, "amount": money(amount), "method": rng.choice(["card", "ach", "card", "card"]),
                         "_k": k})
    clean = [j for j, p in enumerate(payments) if p["_k"] not in special]
    rng.shuffle(clean)
    for k in clean[:12]:                                 # the same payment taken twice within 4 minutes
        p = dict(payments[k])
        pay_no += 1
        p["payment_id"] = f"P{pay_no:06d}"
        p["paid_at"] = p["paid_at"] + dt.timedelta(minutes=rng.randint(1, 4))
        payments.append(p)
    expected["no double-charged payments"] = 12
    for k in clean[12:18]:                               # an extra 00 typed into the amount
        payments[k]["amount"] = money(float(payments[k]["amount"]) * 100)
    expected["payment amount is not extreme"] = 6
    expected["no invoice is paid more than its total"] = 12 + 6
    for j in range(10):
        pay_no += 1
        payments.append({"payment_id": f"P{pay_no:06d}", "invoice_id": f"INV8{j:04d}", "customer_id": "C0001",
                         "paid_at": START + dt.timedelta(days=j * 30, hours=10), "amount": money(100 + j * 7.13),
                         "method": "ach"})
    expected["payment belongs to an invoice"] = 10
    payments.sort(key=lambda p: p["paid_at"])
    for name in ("invoice_id is unique", "payment_id is unique", "payments table is not empty",
                 "payments are recent"):
        expected[name] = 0

    # write -------------------------------------------------------------------------------------------
    OUT.mkdir(exist_ok=True)
    for name, data, cols in (
            ("customers", customers, ["customer_id", "email", "country", "created_at"]),
            ("invoices", invoices, ["invoice_id", "customer_id", "invoice_date", "total", "currency"]),
            ("invoice_lines", lines, ["line_id", "invoice_id", "product", "quantity", "unit_price"]),
            ("payments", payments, ["payment_id", "invoice_id", "customer_id", "paid_at", "amount", "method"])):
        with open(OUT / f"{name}.csv", "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
            w.writeheader()
            for row in data:
                w.writerow({c: ("" if row.get(c) is None else row[c]) for c in cols})
    (OUT / "expected.json").write_text(json.dumps(expected, indent=2), encoding="utf-8")
    print(f"customers {len(customers)}, invoices {len(invoices)}, lines {len(lines)}, payments {len(payments)}")


if __name__ == "__main__":
    main()
