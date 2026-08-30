# BlinkFill examples (country, initials, bracket repair, between-markers)

- **Source:** Rishabh Singh, "BlinkFill: Semi-supervised Programming By Example for Syntactic String Transformations", *PVLDB* 9(10), 2016 — https://doi.org/10.14778/2977797.2977807. Examples 1–4 of the paper, taken from Excel help forums and StackOverflow; the paper evaluates on 207 such real-world tasks. Rows follow the paper's figures (plus two extra rows per column).
- **Tags:** `rsplit` on the last delimiter · first/last word initials with optional middle names · conditional suffix repair · substring between two marker words · CSV column-wise transform
- **Data:** `blinkfill-examples.input.csv` — 6 rows, columns `city_country,name,code,message`.
- **Stdlib used in solution:** `csv`, `sys`
- **Difficulty:** easy (four independent 3–5 minute stages)
- **Shape:** CSV rows → four small string transforms → CSV rows

## Task description (as given to participant)

`blinkfill-examples.input.csv` has four columns; transform each and write a CSV with columns `country,initials,code,extracted`:

1. **city_country** → the country: `Mumbai, India` → `India`; `Los Angeles, United States of America` → `United States of America` (countries can contain spaces).
2. **name** → initials of the *first* and *last* names only: `Brandon Henry Saunders` → `B.S.`, `Dafna Q. Chen` → `D.C.`, `William Lee` → `W.L.`.
3. **code** → medical billing codes should end with `]`; some are missing it. `[CPT-00350` → `[CPT-00350]`, but `[CPT-11536]` must not become `[CPT-11536]]`.
4. **message** → the text between the words `nextData` and `moreInfo`: `nextData 12 Street moreInfo 35` → `12 Street`.

## Expected output

```
country,initials,code,extracted
India,B.S.,[CPT-00350],12 Street
United States of America,W.L.,[CPT-00340],Main
United States,D.C.,[CPT-11536],Albany Street
United States of America,D.S.,[CPT-115],134 Green Street
New Zealand,E.C.,[CPT-2210],Park Ave
India,A.C.,[CPT-0002],7
```

## Notes for study designers

- The paper's point is that each transformation has many plausible "logics" (split on the 2nd alphabetic token vs. after the comma vs. after the last whitespace …), so participants must *choose* a pattern; the rows are designed so naive choices fail: `United States of America` breaks "last word", `Dafna Q. Chen` breaks "second word is the last name", `Ana de la Cruz` breaks "capitalised words only".
- Column 3 is the conditional that FlashFill needed two examples for; in a script it is one `endswith`.
- Good edit-task variants: a starting script using `split(",")[1]` (breaks on a city containing a comma), or `name.split()[1]` for the last initial.
- Compare with `flashfill-transforms` and `gulwani-cacm-strings`; together the three files cover the classic PBE string-benchmark families.

## Example solution

```python
# The four motivating examples from Singh, "BlinkFill" (PVLDB 2016), each
# applied to one CSV column.
import csv, sys

def country(city_country):
    """'Mumbai, India' -> 'India' (everything after the last comma)."""
    return city_country.rsplit(",", 1)[1].strip()

def initials(name):
    """'Brandon Henry Saunders' -> 'B.S.' (first and last word only)."""
    words = name.split()
    return f"{words[0][0]}.{words[-1][0]}."

def close_bracket(code):
    """Append ']' only when it is missing."""
    return code if code.endswith("]") else code + "]"

def between(message, left="nextData", right="moreInfo"):
    """Text strictly between the two marker words, whitespace-trimmed."""
    start = message.index(left) + len(left)
    end = message.index(right, start)
    return message[start:end].strip()

if __name__ == "__main__":
    with open("blinkfill-examples.input.csv", newline="") as f:
        rows = list(csv.DictReader(f))
    out = csv.writer(sys.stdout)
    out.writerow(["country", "initials", "code", "extracted"])
    for r in rows:
        out.writerow([country(r["city_country"]), initials(r["name"]),
                      close_bracket(r["code"]), between(r["message"])])
```
