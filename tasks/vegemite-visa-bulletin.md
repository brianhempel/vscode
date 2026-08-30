# Vegemite: Visa Bulletin priority dates

- **Source:** James Lin, Jeffrey Wong, Jeffrey Nichols, Allen Cypher, Tessa Lau, "End-User Programming of Mashups with Vegemite", IUI 2009 — https://doi.org/10.1145/1502650.1502667. User-study task 3, "Visa Bulletin Dates": *for all of the archived Visa Bulletins, extract a list of the dates they show for the "Employment-based 3rd, All Chargeability Areas" category* (from travel.state.gov). The four bulletins here are synthetic but follow the real bulletin's table layout (`01JAN05`, `C` = current).
- **Tags:** splitting a file into records on blank lines · fixed-width/whitespace table parsing · row-label lookup · `01JAN05` → ISO date conversion · pairwise differences over a sequence
- **Data:** `vegemite-visa-bulletin.input.txt` — 4 monthly bulletins, 6 lines each.
- **Stdlib used in solution:** `datetime`
- **Difficulty:** easy–medium
- **Shape:** text → list of (title, table dict) → strings → dates → numbers

## Task description (as given to participant)

`vegemite-visa-bulletin.input.txt` contains several monthly Visa Bulletins separated by blank lines. Each begins with `Visa Bulletin for <Month> <Year>` and then holds a small table: a header row of chargeability areas and rows labelled `1st`, `2nd`, `3rd`, `Other Workers`, whose cells are either a date written like `01JAN05` (1 January 2005) or `C` (current).

1. For each bulletin, print the bulletin month and the date in the `3rd` row under `All Chargeability Areas`, converted to ISO format (`2005-01-01`), or `current`.
2. Then print, for each bulletin after the first, how many days that date moved compared with the previous bulletin (e.g. `+59 days`).

## Expected output

```
EB-3, All Chargeability Areas:
  January 2008    2005-01-01
  February 2008   2005-01-01
  March 2008      2005-03-01
  April 2008      2005-11-15

Movement since previous bulletin:
  February 2008   +0 days
  March 2008      +59 days
  April 2008      +259 days
```

## Notes for study designers

- The parsing is the interesting part: the row label column contains a space (`Other Workers`), so a naive `split()` misaligns that row; the reference solution slices a fixed label width (23 chars) and splits the rest.
- Two-digit years and month abbreviations make `01JAN05 → 2005-01-01` a small pattern-detection step; `C` is the special case that must be handled before parsing.
- Edit-task variants: extract a different (row, column) pair from a command-line argument; handle a bulletin where the 3rd/All cell is `C` (movement undefined); output CSV instead of a report.
- The real bulletins are public at https://travel.state.gov/content/travel/en/legal/visa-law0/visa-bulletin.html if you want a URL-download variant, though their HTML tables are much messier than this fixture.

## Example solution

```python
# "Visa Bulletin Dates": from a series of monthly bulletins, extract the
# priority date shown for Employment-based 3rd / All Chargeability Areas,
# convert it to ISO form, and compute month-to-month movement.
from datetime import date

MONTHS = {m: i + 1 for i, m in enumerate(
    ["JAN", "FEB", "MAR", "APR", "MAY", "JUN",
     "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"])}

def parse_bulletins(text):
    """Return a list of (bulletin title, {row label: [cells]})."""
    bulletins = []
    for block in text.strip().split("\n\n"):
        lines = block.splitlines()
        title = lines[0].replace("Visa Bulletin for ", "")
        table = {}
        for line in lines[2:]:                    # skip title and header
            label, rest = line[:23].strip(), line[23:]
            table[label] = rest.split()
        bulletins.append((title, table))
    return bulletins

def to_iso(cell):
    """'01JAN05' -> '2005-01-01'; 'C' (current) -> 'current'."""
    if cell == "C":
        return "current"
    day, mon, yy = int(cell[:2]), MONTHS[cell[2:5]], int(cell[5:])
    return date(2000 + yy, mon, day).isoformat()

if __name__ == "__main__":
    with open("vegemite-visa-bulletin.input.txt") as f:
        bulletins = parse_bulletins(f.read())

    print("EB-3, All Chargeability Areas:")
    dates = []
    for title, table in bulletins:
        iso = to_iso(table["3rd"][0])             # column 0 = All Chargeability Areas
        dates.append((title, iso))
        print(f"  {title:<15} {iso}")

    print("\nMovement since previous bulletin:")
    for (prev_title, prev), (title, cur) in zip(dates, dates[1:]):
        delta = (date.fromisoformat(cur) - date.fromisoformat(prev)).days
        print(f"  {title:<15} {delta:+d} days")
```
