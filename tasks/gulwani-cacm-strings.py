# Three string transformations from Gulwani, Harris & Singh (CACM 2012),
# each applied to one column of a CSV: phone normalisation (Ex. 1),
# upper-case-letter abbreviation (Ex. 2), date reformatting (Ex. 4).
import csv, sys

DEFAULT_AREA_CODE = "425"
MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
          "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]

def normalise_phone(s):
    """Keep only digits; 7-digit numbers get the default area code."""
    digits = "".join(ch for ch in s if ch.isdigit())
    if len(digits) == 7:
        digits = DEFAULT_AREA_CODE + digits
    if len(digits) != 10:
        raise ValueError(f"not a phone number: {s!r}")
    return f"{digits[:3]}-{digits[3:6]}-{digits[6:]}"

def abbreviate(s):
    """Concatenate every upper-case letter: 'Principles Of ... Languages' -> 'POPL'.
    (The paper's program loops over UpperTok matches.)"""
    return "".join(ch for ch in s if ch.isupper())

def ordinal(n):
    if 11 <= n % 100 <= 13:
        suffix = "th"
    else:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"

def reformat_date(s):
    """'6-3-2008' (M-D-YYYY) -> 'Jun 3rd, 2008'."""
    month, day, year = (int(part) for part in s.split("-"))
    return f"{MONTHS[month - 1]} {ordinal(day)}, {year}"

with open("gulwani-cacm-strings.input.csv", newline="") as f:
    rows = list(csv.DictReader(f))
out = csv.writer(sys.stdout)
out.writerow(["phone", "abbreviation", "date"])
for row in rows:
    out.writerow([normalise_phone(row["phone"]),
                  abbreviate(row["name"]),
                  reformat_date(row["date"])])
