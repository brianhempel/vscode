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

if __name__ == "__main__":
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
