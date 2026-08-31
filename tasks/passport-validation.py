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
