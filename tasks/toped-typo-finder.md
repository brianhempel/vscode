# Toped typo finder (soft-constraint data validation)

- **Source:** Christopher Scaffidi, Brad Myers, Mary Shaw, "Topes: Reusable Abstractions for Validating Data" (ICSE 2008, https://doi.org/10.1145/1368088.1368090) and the Toped user study in Scaffidi, Myers, Shaw, "Toped: Enabling End-User Programmers to Validate Data" (VL/HCC 2008 — https://doi.org/10.1109/VLHCC.2008.4639072). In that study administrative assistants and graduate students had to "find typos" in three columns of strings drawn from the EUSES spreadsheet corpus: US phone numbers, street addresses (e.g. `1000 EVANS AVE.` vs. the non-address `12 MILES NORTH OF INDEPENDENCE`) and company names. Toped's key idea, from a pilot study of how end users describe data: a format is a sequence of *named parts* with constraints that are **always** or only **usually** true (soft constraints), and violations are explained in English. The strings here are our own, in the shape of those columns.
- **Tags:** small-pattern detection on strings · character-class tests · named parts with hard/soft constraints · three-way classification · block-structured input · English explanations
- **Data:** `toped-typo-finder.input.txt` — three `## …` blocks of 8 strings each (phone, address, company).
- **Stdlib used in solution:** none beyond builtins
- **Difficulty:** medium
- **Shape:** text blocks → per-string list of violated constraints → formatted report. Not a data-processing task in the aggregate sense: it is a *validator*.

## Task description (as given to participant)

`toped-typo-finder.input.txt` contains three blocks of strings, headed `## phone`, `## address` and `## company`. Some are fine, some contain typos, and some are not the kind of data they should be. Write a script that defines a *format* for each kind as a list of constraints, where each constraint is either **hard** ("must …") or **soft** ("usually …"), and prints for each string:

- `VALID` if no constraint is violated,
- `QUESTIONABLE` if only soft constraints are violated,
- `INVALID` if any hard constraint is violated,

followed by the English text of every violated constraint, separated by `; `. Suggested constraints (you may refine them):

- **phone**: must contain only digits and punctuation; must have exactly 10 digits (a leading `1` country code is allowed but *usually* absent); parts are *usually* separated by hyphens.
- **address**: must start with a house number (*usually* all digits); must contain a street type such as `AVE`, `ST`, `BLVD`, `RD`, `DR`; *usually* has number + street name + type; *usually* no more than 5 words.
- **company**: must not be empty; *usually* not all capitals; *usually* starts with a capital letter; *usually* at most one legal suffix (`Corp`, `Inc`, `LLC`, `Ltd`, `Co`); *usually* no `&`.

## Expected output

```
[phone]
  VALID        412-268-1234
  QUESTIONABLE (412) 268 1234                   parts are usually separated by hyphens
  QUESTIONABLE 412.268.1234                     parts are usually separated by hyphens
  INVALID      412-268-12345                    must have 10 digits (has 11)
  INVALID      268-1234                         must have 10 digits (has 7)
  INVALID      412-ABC-1234                     must contain only digits and punctuation; must have 10 digits (has 7)
  QUESTIONABLE 1-412-268-1234                   usually has no leading country code
  INVALID      412-268-1234 ext. 12             must contain only digits and punctuation; must have 10 digits (has 12)

[address]
  VALID        1000 EVANS AVE.
  INVALID      12 MILES NORTH OF INDEPENDENCE   must contain a street type such as AVE, ST or BLVD
  VALID        5000 Forbes Avenue
  QUESTIONABLE 221B Baker St                    house number is usually all digits
  INVALID      P.O. Box 1234                    must start with a house number; must contain a street type such as AVE, ST or BLVD
  VALID        1600 Pennsylvania Ave NW
  INVALID      Forbes Avenue 5000               must start with a house number
  VALID        7 Elm Blvd

[company]
  VALID        Acme Corp.
  QUESTIONABLE ACME CORP                        usually not all capitals
  QUESTIONABLE Acme Corp. Inc. LLC              usually has at most one legal suffix
  VALID        Wayne Enterprises
  QUESTIONABLE initech                          usually starts with a capital letter
  VALID        Stark Industries, Inc.
  VALID        Globex
  QUESTIONABLE Tyrell Corporation & Sons        usually contains no '&'

```

## Notes for study designers

- This is the study's task with the ecological validity of "validate a spreadsheet column"; the three kinds run from highly structured (phone) to nearly unstructured (company name), exactly as in the paper.
- The soft/hard distinction is the interesting design: the script has to *collect* violations rather than return on the first failure, and the verdict is computed from the collected lists (list → string).
- Edit-task variants: add a fourth block (`## email` or `## date`) with its own format; change the policy so that ≥2 soft violations count as INVALID; make the phone checker accept extensions (`ext. 12`) by splitting them off before counting digits — currently a deliberate false negative.
- Regex is a natural alternative for the phone format; the paper argues end users find regexes hard to read, which is why the reference solution uses explicit named checks.

## Example solution

```python
# Toped-style data validation: each format is a list of named parts, each
# with hard ("always") and soft ("usually") constraints. A string is VALID,
# QUESTIONABLE (only soft constraints violated) or INVALID, and every
# violated constraint is reported in plain English.

STREET_TYPES = {"AVE", "AVENUE", "ST", "STREET", "BLVD", "BOULEVARD",
                "RD", "ROAD", "DR", "DRIVE", "LN", "LANE", "WAY", "CIRCLE"}
COMPANY_SUFFIXES = {"CORP", "CORPORATION", "INC", "LLC", "LTD", "CO"}

def check_phone(s):
    """Parts: area code (3 digits), exchange (3 digits), number (4 digits)."""
    hard, soft = [], []
    digits = "".join(ch for ch in s if ch.isdigit())
    if digits.startswith("1") and len(digits) == 11:
        digits = digits[1:]
        soft.append("usually has no leading country code")
    if any(ch.isalpha() for ch in s):
        hard.append("must contain only digits and punctuation")
    if len(digits) != 10:
        hard.append(f"must have 10 digits (has {len(digits)})")
    if "-" not in s:
        soft.append("parts are usually separated by hyphens")
    return hard, soft

def check_address(s):
    """Parts: number, street name, street type."""
    hard, soft = [], []
    words = s.replace(".", "").split()
    if not words or not words[0][0].isdigit():
        hard.append("must start with a house number")
    elif not words[0].isdigit():
        soft.append("house number is usually all digits")
    if len(words) < 3:
        soft.append("usually has number, street name and street type")
    if not any(w.upper() in STREET_TYPES for w in words[1:]):
        hard.append("must contain a street type such as AVE, ST or BLVD")
    if len(words) > 5:
        soft.append("usually no more than 5 words")
    return hard, soft

def check_company(s):
    """Parts: name words, optional legal suffix."""
    hard, soft = [], []
    words = s.replace(".", "").replace(",", "").split()
    if not words:
        hard.append("must not be empty")
    if s == s.upper():
        soft.append("usually not all capitals")
    if s[:1].islower():
        soft.append("usually starts with a capital letter")
    suffixes = [w for w in words if w.upper() in COMPANY_SUFFIXES]
    if len(suffixes) > 1:
        soft.append("usually has at most one legal suffix")
    if "&" in s:
        soft.append("usually contains no '&'")
    return hard, soft

CHECKERS = {"phone": check_phone, "address": check_address, "company": check_company}

def parse_blocks(text):
    blocks, current = {}, None
    for line in text.splitlines():
        if line.startswith("## "):
            current = line[3:].strip()
            blocks[current] = []
        elif line.strip() and current is not None:
            blocks[current].append(line.strip())
    return blocks

with open("toped-typo-finder.input.txt") as f:
    blocks = parse_blocks(f.read())
for kind, strings in blocks.items():
    print(f"[{kind}]")
    for s in strings:
        hard, soft = CHECKERS[kind](s)
        verdict = "INVALID" if hard else "QUESTIONABLE" if soft else "VALID"
        reasons = "; ".join(hard + soft)
        print(f"  {verdict:<12} {s:<32} {reasons}".rstrip())
    print()
```
