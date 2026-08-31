# FlashFill-style string transforms

- **Source:** Sumit Gulwani, "Automating String Processing in Spreadsheets Using Input-Output Examples", POPL 2011 — https://www.microsoft.com/en-us/research/publication/automating-string-processing-spreadsheets-using-input-output-examples/ (the FlashFill paper). The three columns correspond to the paper's motivating examples: Example 1 (extract the quantity from product descriptions such as `BTR KRNL WK CORN 15Z`), Example 4 (phone numbers in inconsistent formats → `(323)-708-7700`), and the name-formatting examples (`Dr. Eran Yahav` → `Yahav, E.`). The same tasks appear as `phone-*`, `name-combine*`, `dr-name` etc. in the SyGuS PBE-Strings benchmark track (https://sygus-org.github.io/). Names/phones are the paper's illustrative values plus made-up rows in the same style; product strings follow the paper's examples.
- **Tags:** CSV read/write · per-column string normalisation · token classification · titles/suffixes/particles · digit extraction
- **Data:** `flashfill-transforms.input.csv` — header + 10 rows, columns `name,phone,product`.
- **Stdlib used in solution:** `csv`, `sys`
- **Difficulty:** medium
- **Shape:** CSV rows → per-field string transforms → CSV rows

## Task description (as given to participant)

`flashfill-transforms.input.csv` has three columns. Write a script that reads it and writes a new CSV (to stdout) with columns `short_name,phone,weight` where:

1. **short_name**: `Last, F.` — the last name followed by the first initial. Drop titles (`Dr.`, `Mr.`, …) and suffixes (`Sr.`, `Jr.`, …). Lower-case particles such as `de`, `van`, `von` belong to the last name (`Oege de Moor` → `de Moor, O.`).
2. **phone**: normalised to `(NNN)-NNN-NNNN` regardless of the input's separators, and ignoring a leading `1` / `+1` country code.
3. **weight**: the size/weight token from the product description — a number followed by `OZ`, `Z` or `LB`, either glued (`15Z`) or separated by a space (`3.6 OZ`); if there is no weight, fall back to a pack count (`1 PK`). Return it exactly as written in the input.

Fields containing a comma must be quoted correctly in the output CSV.

## Expected output

```
short_name,phone,weight
"Yahav, E.",(323)-708-7700,15Z
"Gates, B.",(425)-706-7709,3.6 OZ
"de Moor, O.",(510)-220-5586,1 PK
"FreeHafer, N.",(425)-235-7654,5 Z
"McMillan, K.",(425)-706-7709,6 OZ
"Lopez, K.",(206)-555-0143,20Z
"Cencini, A.",(206)-555-0198,12Z
"Kotas, J.",(425)-555-0102,26 OZ
"Sergienko, M.",(425)-555-0184,2LB
"Thorpe, S.",(425)-555-0119,8 OZ
```

## Notes for study designers

- Each column is an independent "FlashFill"-sized sub-task, so the task decomposes naturally into three stages plus the CSV plumbing; you can drop columns to shorten it.
- Traps: `Bill Gates Sr.` (suffix), `Kathy J. Lopez` (middle initial), `JUMBO ZIPLOC 2 PK 20Z` (both a pack count and a weight — weight wins), `FRENCH WORCESTERSHIRE 5 Z` (unit as a separate token), `+1 (206) 555 0143` (country code + mixed separators), and the output field `Yahav, E.` containing a comma (needs `csv.writer` or manual quoting — a nice bug to find if a first version prints with f-strings).
- Because the source is a programming-by-example paper, this task also works as an "input/output examples only" condition: show participants the expected output and let them infer the rules.
- Extension: add a `date` column with mixed formats (`2/3/2010`, `Feb 3, 2010`, `2010-02-03`) → ISO, which FlashFill famously could *not* do.

## Example solution

```python
# FlashFill-style transforms: names -> "Last, F.", phones -> "(NNN)-NNN-NNNN", products -> weight token.
import csv
import sys

SUFFIXES = {"sr.", "jr.", "sr", "jr", "ii", "iii", "iv"}
TITLES = {"dr.", "mr.", "mrs.", "ms.", "prof.", "dr", "mr", "mrs", "ms", "prof"}
PARTICLES = {"de", "van", "von", "der", "da", "di", "la", "le"}

def format_name(name):
    """'Dr. Eran Yahav' -> 'Yahav, E.'; 'Oege de Moor' -> 'de Moor, O.'"""
    tokens = [t.strip(",") for t in name.split()]
    tokens = [t for t in tokens if t.lower() not in TITLES and t.lower() not in SUFFIXES]
    first = tokens[0]
    # Last name = last token, plus any lowercase particles directly before it.
    last_parts = [tokens[-1]]
    i = len(tokens) - 2
    while i > 0 and tokens[i].lower() in PARTICLES:
        last_parts.insert(0, tokens[i])
        i -= 1
    return f"{' '.join(last_parts)}, {first[0].upper()}."

def format_phone(phone):
    """Any separators, optional leading 1 -> '(323)-708-7700'."""
    digits = "".join(ch for ch in phone if ch.isdigit())
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]
    return f"({digits[:3]})-{digits[3:6]}-{digits[6:]}"

def is_number(s):
    return s != "" and s.replace(".", "", 1).isdigit()

def extract_weight(product):
    """Find the size token: a number followed by OZ/Z/LB (weight), else PK (count).
    The number and unit may be one token ('15Z') or two ('3.6 OZ')."""
    tokens = product.split()
    for unit in ("OZ", "Z", "LB", "PK"):        # priority order
        for i, tok in enumerate(tokens):
            if not tok.endswith(unit):
                continue
            number = tok[: -len(unit)]
            if is_number(number):                  # "15Z", "3.6OZ"
                return tok
            if number == "" and i > 0 and is_number(tokens[i - 1]):   # "3.6 OZ"
                return tokens[i - 1] + " " + unit
    return ""

with open("flashfill-transforms.input.csv", newline="") as f:
    rows = list(csv.DictReader(f))

writer = csv.writer(sys.stdout)
writer.writerow(["short_name", "phone", "weight"])
for r in rows:
    writer.writerow([format_name(r["name"]), format_phone(r["phone"]), extract_weight(r["product"])])
```
