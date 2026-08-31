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
