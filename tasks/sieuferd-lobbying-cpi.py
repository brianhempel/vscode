# Lobbying totals per ethanol producer: join plants with quarterly lobbying
# reports, sort reports most-recent-first, add inflation-adjusted amounts via
# a CPI table, and exclude superseded (amended) reports.
import csv

def load(name):
    with open(f"sieuferd-lobbying-cpi.{name}.csv", newline="") as f:
        return list(csv.DictReader(f))

plants = load("plants")
lobbying = load("lobbying")
cpi = {row["cyear"]: float(row["cpiv"]) for row in load("cpi")}

QUARTER = {"Q1": 1, "Q2": 2, "Q3": 3, "Q4": 4}

def reports_for(company, include_superseded=False):
    """Nested child relation: the lobbying reports of one company,
    sorted by year descending then quarter descending."""
    reps = [r for r in lobbying
            if r["ultorg"] == company and (include_superseded or r["luse"] == "y")]
    reps.sort(key=lambda r: (int(r["lyear"]), QUARTER[r["ltype"]]), reverse=True)
    for r in reps:
        r["amount"] = float(r["amount"])
        r["adjusted"] = r["amount"] / cpi[r["lyear"]]   # 2012 dollars
    return reps

print(f"{'Company':<22} {'Reports':>7} {'Raw total':>12} {'Adj. total':>12} {'Latest':>8}")
grand_raw = grand_adj = 0.0
for p in plants:
    reps = reports_for(p["company"])
    raw = sum(r["amount"] for r in reps)
    adj = sum(r["adjusted"] for r in reps)
    latest = f"{reps[0]['lyear']} {reps[0]['ltype']}" if reps else "-"
    print(f"{p['company']:<22} {len(reps):>7} {raw:>12,.0f} {adj:>12,.0f} {latest:>8}")
    grand_raw += raw
    grand_adj += adj
print(f"{'TOTAL':<22} {'':>7} {grand_raw:>12,.0f} {grand_adj:>12,.0f}")
print()
# Show the nested relation for one company, including the superseded report.
company = "Prairie Ethanol Corp"
print(f"Reports for {company} (most recent first; * = superseded, excluded):")
for r in reports_for(company, include_superseded=True):
    flag = "*" if r["luse"] == "n" else " "
    print(f"  {flag} {r['lyear']} {r['ltype']}  {r['amount']:>9,.0f}  -> {r['adjusted']:>9,.0f} (2012 $)")
