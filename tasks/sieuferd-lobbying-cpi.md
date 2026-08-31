# SIEUFERD lobbying totals with inflation adjustment

- **Source:** Eirik Bakke & David R. Karger, "Expressive Query Construction through Direct Manipulation of Nested Relational Results", SIGMOD 2016 — https://doi.org/10.1145/2882903.2915210 , §1.1 motivating example, and Bakke's MIT PhD thesis (2016) standardized tasks 1–2 ("Lobbying": manual join + totals formula; then inflation-corrected totals via a CPI table). The original scenario came from an investigative journalist's story on ethanol-industry lobbying, using the Center for Responsive Politics lobbying database joined with the journalist's own list of ethanol plants. Table and column names (`plants_os`, `lobbying.ultorg/lyear/ltype/amount/luse`, `cpi.cyear/cpiv`) follow the paper; all values here are synthetic and the company names are invented (rather than the real ethanol producers, so that no fabricated lobbying amounts are attached to real companies).
- **Tags:** CSV join on differently named keys · group-by with nested child lists · multi-key sort (year desc, quarter desc) · per-row formula (CPI adjustment) · filtering superseded rows · formatted table with totals
- **Data:** `sieuferd-lobbying-cpi.plants.csv` (5 companies), `sieuferd-lobbying-cpi.lobbying.csv` (17 quarterly reports, 2 marked superseded, one for a company not in the plants list), `sieuferd-lobbying-cpi.cpi.csv` (7 years, 2012 = 1.0).
- **Stdlib used in solution:** `csv`
- **Difficulty:** easy–medium (~15 minutes)
- **Shape:** two flat tables → one-to-many nested lists → numbers → formatted table

## Task description (as given to participant)

Three CSV files describe lobbying by ethanol producers:

- `…plants.csv` — `company,state,capacity_mgy`: the producers we care about.
- `…lobbying.csv` — `ultorg,lyear,ltype,amount,luse`: quarterly lobbying reports; `ultorg` is the company name, `ltype` is `Q1`–`Q4`, and `luse` is `n` for a report that was later **superseded** by an amended one (it must be excluded from totals to avoid double counting).
- `…cpi.csv` — `cyear,cpiv`: consumer price index per year, normalised so 2012 = 1.0.

Write a script that:

1. Joins each company in `plants.csv` to its reports (`plants.company = lobbying.ultorg`); reports for a company are ordered most-recent-first (year, then quarter, descending). Reports for companies not in `plants.csv` are ignored; companies with no reports still appear with zero.
2. Prints one table row per company: number of (non-superseded) reports, raw total, inflation-adjusted total in 2012 dollars (`amount / cpiv` of the report's year), and the year+quarter of the latest report; then a `TOTAL` row.
3. Prints, for **Prairie Ethanol Corp**, the full list of its reports most-recent-first, marking the superseded one with `*`, with raw and adjusted amounts.

## Expected output

```
Company                Reports    Raw total   Adj. total   Latest
Prairie Ethanol Corp         5      265,000      271,975  2012 Q2
Cornbelt Biofuels            4      105,000      123,797  2012 Q1
Dakota Prairie Fuels         0            0            0        -
Valley Renewables            4      485,000      508,215  2012 Q3
Heartland Distillers         1       10,000       10,225  2011 Q4
TOTAL                               865,000      914,212

Reports for Prairie Ethanol Corp (most recent first; * = superseded, excluded):
    2012 Q2     70,000  ->    70,000 (2012 $)
  * 2011 Q3     55,000  ->    56,237 (2012 $)
    2011 Q3     60,000  ->    61,350 (2012 $)
    2011 Q1     55,000  ->    56,237 (2012 $)
    2010 Q4     40,000  ->    42,194 (2012 $)
    2010 Q2     40,000  ->    42,194 (2012 $)
```

## Notes for study designers

- Mirrors the paper's sequence exactly: Join → Sort descending by `lyear` then `ltype` → aggregate formula (sum) → second join (`cpi`) → scalar formula → Filter `luse = n`. Each of those is one edit to the script, so the task decomposes into a chain of small "add one thing" edits — ideal for a script-*editing* study.
- Gotchas to exploit: the join keys have different names (`company` vs `ultorg`); `ltype` sorts wrongly as a plain string only if you use more than nine quarters (it doesn't here — a plausible red herring), but `lyear` must be converted to `int` if you go beyond string-comparable years; the superseded report has the same year+quarter as its replacement; one company has no reports; one report belongs to a company not in the plants list (should be ignored — an inner join, not a left join from lobbying).
- Extensions: yearly subtotals per company (nested group-by two levels deep), a `Big Oil Holdings`-style "who is *not* in our list" report, or reading the CPI table from a URL.

## Example solution

```python
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
```
