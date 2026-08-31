# Housing prices: long table ↔ year × month crosstab

- **Source:** Sean Kandel et al., "Wrangler: Interactive Visual Specification of Data Transformation Scripts", CHI 2011 — http://vis.stanford.edu/files/2011-Wrangler-CHI.pdf . This is the paper's user-study **Task 2**: participants started with three columns of housing data (`year`, `month`, `price`) and had to produce a cross-tab with one row per year and the 12 months as columns (Wrangler's *unfold* operator). We add the inverse (*fold*) as a second stage. Prices are **synthetic**.
- **Tags:** CSV parsing · dict-of-dicts pivot · fixed column order with missing cells · inverse transform / round-trip check
- **Data:** `wrangler-housing-crosstab.input.csv` — header + 21 rows (2009 complete, 2010 with three months missing).
- **Stdlib used in solution:** `csv`
- **Difficulty:** easy–medium
- **Shape:** long CSV → nested dict → wide CSV text → back to long rows

## Task description (as given to participant)

`wrangler-housing-crosstab.input.csv` has columns `year,month,price` (month as a three-letter abbreviation) with one row per month. Write a script that:

1. prints a cross-tab as CSV: header `year,Jan,Feb,…,Dec`, then one row per year with that year's prices in month order, leaving the cell **empty** when a month is missing;
2. converts the cross-tab text back into long `(year, month, price)` rows (skipping empty cells), and prints how many rows that produced, whether the round trip reproduces the original rows exactly, and which `year-month` combinations are missing.

## Expected output

```
year,Jan,Feb,Mar,Apr,May,Jun,Jul,Aug,Sep,Oct,Nov,Dec
2009,180500,181200,179900,182400,184000,186700,187300,186900,185100,183800,182600,181900
2010,182200,183000,184500,187100,189600,191200,190800,,188400,187200,,

Refolded rows: 21 (original: 21)
Round trip matches original: True
Missing months: 2010-Aug, 2010-Nov, 2010-Dec
```

## Notes for study designers

- The pivot is the nested-dict step (`{year: {month: price}}`); the string step is rendering rows with a fixed month order and blanks for gaps (`dict.get(m, "")`). The inverse stage forces participants to parse their own output.
- Gotchas: months must be in calendar order, not alphabetical or first-seen order; missing months must produce empty cells, not shifted columns; the round-trip comparison only holds if the fold preserves the original row order (years, then months).
- Being a timed task from a CHI user study, it has known baseline difficulty (Wrangler participants were compared against Excel).
- Extensions: compute year-over-year change per month; accept numeric months (`1`–`12`) as well as names; output a Markdown table instead of CSV.

## Example solution

```python
# Wrangler task 2: long (year,month,price) -> crosstab (one row per year, 12 month columns) and back.
import csv

MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]

def unfold(long_rows):
    """Long rows -> {year: {month: price}}"""
    table = {}
    for r in long_rows:
        table.setdefault(r["year"], {})[r["month"]] = r["price"]
    return table

def render_crosstab(table):
    lines = ["year," + ",".join(MONTHS)]
    for year in sorted(table):
        cells = [table[year].get(m, "") for m in MONTHS]   # blank for missing months
        lines.append(year + "," + ",".join(cells))
    return "\n".join(lines)

def fold(crosstab_text):
    """Inverse: crosstab CSV text -> list of (year, month, price) skipping blanks."""
    rows = []
    reader = csv.DictReader(crosstab_text.splitlines())
    for r in reader:
        for m in MONTHS:
            if r[m] != "":
                rows.append((r["year"], m, r[m]))
    return rows

with open("wrangler-housing-crosstab.input.csv", newline="") as f:
    long_rows = list(csv.DictReader(f))

table = unfold(long_rows)
crosstab = render_crosstab(table)
print(crosstab)

print()
refolded = fold(crosstab)
print(f"Refolded rows: {len(refolded)} (original: {len(long_rows)})")
original = [(r["year"], r["month"], r["price"]) for r in long_rows]
print("Round trip matches original:", refolded == original)
missing = [f"{y}-{m}" for y in sorted(table) for m in MONTHS if m not in table[y]]
print("Missing months:", ", ".join(missing))
```
