# Regex variant of phone-email-extractor.py (same output). This is close to
# how "Automate the Boring Stuff" ch. 7 solves it.
import re

PHONE = re.compile(r"""
    (?<![\d#])                 # not preceded by a digit or '#'
    (?:\+?1[\s.-]?)?           # optional country code
    \(?(\d{3})\)?              # area code, optional parentheses
    [\s.-]                     # a separator is required (rules out bare 10-digit runs)
    (\d{3})
    [\s.-]
    (\d{4})
    (?!\d)                     # not followed by another digit
""", re.VERBOSE)

EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+")

def unique(items):
    seen, out = set(), []
    for x in items:
        if x not in seen:
            seen.add(x)
            out.append(x)
    return out

with open("phone-email-extractor.input.txt") as f:
    text = f.read()
phones = unique("-".join(m.groups()) for m in PHONE.finditer(text))
emails = unique(EMAIL.findall(text))
print(f"Phone numbers ({len(phones)}):")
for p in phones:
    print("  " + p)
print(f"Emails ({len(emails)}):")
for e in emails:
    print("  " + e)
