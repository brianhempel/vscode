# Gulwani CACM string examples (phones, abbreviations, dates)

- **Source:** Sumit Gulwani, William R. Harris, Rishabh Singh, "Spreadsheet Data Manipulation Using Examples", *Communications of the ACM* 55(8), 2012 — https://doi.org/10.1145/2240236.2240260. Examples 1, 2 and 4 of the paper, each of which the authors took from a real Excel help-forum thread (the "Advanced Text Formula" and date-format threads). These are the canonical motivating examples of the FlashFill line of programming-by-example work. Data rows are our own, in the shape of the paper's tables.
- **Tags:** digit filtering · default-value conditional · character-class filtering (upper-case runs) · date parsing · ordinal suffix rule · CSV column-wise transform
- **Data:** `gulwani-cacm-strings.input.csv` — 6 rows, columns `phone,name,date`.
- **Stdlib used in solution:** `csv`, `sys`
- **Difficulty:** easy (three independent 5-minute stages)
- **Shape:** CSV rows → three per-column string transforms → CSV rows

## Task description (as given to participant)

`gulwani-cacm-strings.input.csv` has three columns. Write a script that transforms each column and writes a new CSV (`phone,abbreviation,date`) to standard output:

1. **phone** — numbers appear as `323-708-7700`, `(425)-706-7709`, `510.220.5586`, `235 7654`, `745-8139`, `(206) 555-0142`. Normalise every one to `NNN-NNN-NNNN`. A number with only 7 digits is missing its area code: use the default area code `425`.
2. **name** — produce the abbreviation made of every upper-case letter in the name, e.g. `Principles Of Programming Languages` → `POPL`, `Foundations of Software Engineering` → `FSE`.
3. **date** — dates are `M-D-YYYY`, e.g. `6-3-2008`. Rewrite as `Jun 3rd, 2008`: three-letter month, day with ordinal suffix (`1st`, `2nd`, `3rd`, `4th`, … but `11th`, `12th`, `13th`, `21st`, `22nd`), comma, four-digit year.

## Expected output

```
phone,abbreviation,date
323-708-7700,ACM,"Jun 3rd, 2008"
425-706-7709,POPL,"Mar 26th, 2010"
510-220-5586,FSE,"Aug 1st, 2009"
425-235-7654,UIST,"Sep 24th, 2007"
425-745-8139,HFCS,"Nov 11th, 2011"
206-555-0142,ICSE,"Dec 22nd, 2012"
```

## Notes for study designers

- Each column is exactly one of the paper's examples: Ex. 1 (phones; the conditional "add 425 if 7 digits" is the interesting part), Ex. 2 (the paper's synthesised program is `Loop(Concatenate(SubStr2(v1, UpperTok, w)))`, i.e. concatenate upper-case runs — not "first letter of each word"; the input names are capitalised so the two readings differ for `of`/`in`/`on`), Ex. 4 (dates; the paper solves it with lookup tables for month names and ordinal suffixes, which is a nice alternative to the `11–13` special case).
- The CSV output quotes `"Jun 3rd, 2008"` because of the comma — a small gotcha if participants print with `",".join`.
- Good starting-code bug for an *edit* task: an ordinal function without the `11th/12th/13th` rule, or a phone normaliser that drops the country code `1` incorrectly when a number is written `1-425-…`.
- Compare with `flashfill-transforms` (POPL 2011 examples) and `blinkfill-examples` (PVLDB 2016).

## Example solution

```python
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

if __name__ == "__main__":
    with open("gulwani-cacm-strings.input.csv", newline="") as f:
        rows = list(csv.DictReader(f))
    out = csv.writer(sys.stdout)
    out.writerow(["phone", "abbreviation", "date"])
    for row in rows:
        out.writerow([normalise_phone(row["phone"]),
                      abbreviate(row["name"]),
                      reformat_date(row["date"])])
```
