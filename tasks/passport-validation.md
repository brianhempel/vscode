# Passport field validation

- **Source:** Paraphrased from Advent of Code 2020, day 4 ("Passport Processing") — https://adventofcode.com/2020/day/4. AoC asks that puzzle text and inputs not be copied, so the wording is our own and `passport-validation.input.txt` is a small synthetic input we wrote (the field rules are the puzzle's). AoC puzzles are an established source for program-synthesis and LLM benchmarks (e.g. several PSB2 problems come from AoC), which supports ecological validity.
- **Tags:** blank-line-separated records · `key:value` parsing into dicts · required-key check · per-field value validation (ranges, units, hex colour, fixed-width digits) · table of rules
- **Data:** `passport-validation.input.txt` — 12 records over ~35 lines.
- **Stdlib used in solution:** none beyond builtins
- **Difficulty:** medium (~20 minutes; stage 1 alone is easy)
- **Shape:** text → list of dicts → two filtering stages → summary strings. Small string-pattern detection on every field.

## Task description (as given to participant)

`passport-validation.input.txt` contains a batch of "passport" records. Each record is a set of `key:value` pairs separated by spaces **or newlines**; records are separated by **blank lines**:

```
ecl:gry pid:860033327 eyr:2020 hcl:#fffffd
byr:1937 iyr:2017 cid:147 hgt:183cm

iyr:2013 ecl:amb cid:350 eyr:2023 pid:028048884
hcl:#cfa07d byr:1929
```

**Stage 1.** A record is *complete* if it contains all of `byr iyr eyr hgt hcl ecl pid`. `cid` is optional. Count the complete records.

**Stage 2.** A record is *valid* if it is complete **and** every field obeys its rule:

| field | rule |
|---|---|
| `byr` | four digits, 1920–2002 |
| `iyr` | four digits, 2010–2020 |
| `eyr` | four digits, 2020–2030 |
| `hgt` | a number followed by `cm` (150–193) or `in` (59–76) |
| `hcl` | `#` followed by exactly six characters from `0-9a-f` |
| `ecl` | exactly one of `amb blu brn gry grn hzl oth` |
| `pid` | exactly nine digits (leading zeros allowed) |

Print the number of records, the stage-1 count, the stage-2 count, the `pid`s of the valid records, and — for each complete-but-invalid record — which fields fail.

## Expected output

```
Records: 12
Stage 1 (all required fields present): 10
Stage 2 (all values valid): 6
Valid pids: 860033327, 760753108, 087499704, 896056539, 545766238, 093154719
  pid 186cm: fails eyr, hgt, pid
  pid 012533040: fails eyr
  pid 021572410: fails hcl
  pid 3556412378: fails byr, iyr, eyr, hgt, hcl, ecl, pid
```

## Notes for study designers

- Natural stages: (1) split on `\n\n`, then on whitespace, then on the first `:`; (2) required-key check; (3) one small validator per field — this is where most of the "detect simple patterns in strings" work is (`isdigit`, length checks, suffix check for units, set-membership for hex); (4) filter and report.
- The data deliberately includes a value-swapped record (`hgt:170 pid:186cm`), a `hcl` missing its `#`, a 10-digit `pid`, and a record where *every* field fails, so each validator gets exercised.
- Good "edit" variants: start participants from the stage-1 script and ask them to add stage 2; add a rule (`cid` if present must be 3 digits); make the report a CSV.
- Using a dict of `field → validator function` is the idiomatic Python shape and a nice thing to see participants converge on (or be given and extend).

## Example solution

```python
# Passport validation: parse blank-line-separated key:value records and validate them.

REQUIRED = ["byr", "iyr", "eyr", "hgt", "hcl", "ecl", "pid"]   # "cid" is optional
EYE_COLOURS = {"amb", "blu", "brn", "gry", "grn", "hzl", "oth"}
HEX_DIGITS = set("0123456789abcdef")

def parse_records(text):
    records = []
    for block in text.strip().split("\n\n"):
        fields = {}
        for pair in block.split():
            key, value = pair.split(":", 1)
            fields[key] = value
        records.append(fields)
    return records

def has_required_fields(rec):
    return all(k in rec for k in REQUIRED)

def year_in(value, lo, hi):
    return len(value) == 4 and value.isdigit() and lo <= int(value) <= hi

def valid_height(value):
    number, unit = value[:-2], value[-2:]
    if not number.isdigit():
        return False
    if unit == "cm":
        return 150 <= int(number) <= 193
    if unit == "in":
        return 59 <= int(number) <= 76
    return False

def valid_hair(value):
    return len(value) == 7 and value[0] == "#" and set(value[1:]) <= HEX_DIGITS

RULES = {
    "byr": lambda v: year_in(v, 1920, 2002),
    "iyr": lambda v: year_in(v, 2010, 2020),
    "eyr": lambda v: year_in(v, 2020, 2030),
    "hgt": valid_height,
    "hcl": valid_hair,
    "ecl": lambda v: v in EYE_COLOURS,
    "pid": lambda v: len(v) == 9 and v.isdigit(),
}

def fully_valid(rec):
    return has_required_fields(rec) and all(RULES[k](rec[k]) for k in RULES)

with open("passport-validation.input.txt") as f:
    records = parse_records(f.read())

stage1 = [r for r in records if has_required_fields(r)]
stage2 = [r for r in records if fully_valid(r)]

print(f"Records: {len(records)}")
print(f"Stage 1 (all required fields present): {len(stage1)}")
print(f"Stage 2 (all values valid): {len(stage2)}")
print("Valid pids:", ", ".join(r["pid"] for r in stage2))
for r in records:
    if has_required_fields(r) and not fully_valid(r):
        bad = [k for k in RULES if not RULES[k](r[k])]
        print(f"  pid {r['pid']}: fails {', '.join(bad)}")
```
