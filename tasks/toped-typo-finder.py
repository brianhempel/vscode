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
