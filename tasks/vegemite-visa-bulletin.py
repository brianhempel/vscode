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
