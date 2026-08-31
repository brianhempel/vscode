# Phone number and email extractor

- **Source:** *Automate the Boring Stuff with Python* (Al Sweigart), 2nd ed., Chapter 7 project "Phone Number and Email Address Extractor" — https://automatetheboringstuff.com/2e/chapter7/ . The book solves it with regular expressions; the reference solution below does it **without** `re` (pure string scanning), and a regex variant that prints identical output is in `phone-email-extractor.regex.py` (also appended at the end of this file). Either approach is acceptable for participants. The contact page text is our own synthetic text (the book uses the No Starch Press contact page).
- **Tags:** pattern detection in free text · character-class scanning · normalisation · de-duplication preserving order
- **Data:** `phone-email-extractor.input.txt` — 16 lines of "contact page" text with phone numbers in six different formats, seven emails, and three decoys.
- **Stdlib used in solution:** none beyond builtins
- **Difficulty:** medium
- **Shape:** unstructured text → lists of normalised strings

## Task description (as given to participant)

`phone-email-extractor.input.txt` is the text of a company "Contact us" web page. It contains US phone numbers written in a variety of styles, e.g.

```
415-555-1011      (415) 555-9999      415.555.0000
415 555 3333 ext 4      +1 415-555-1011
```

and email addresses, sometimes wrapped in `<…>` or `(…)` or followed by a comma.

Write a script that prints every phone number normalised to the form `NNN-NNN-NNNN` and every email address, each list de-duplicated and in order of first appearance, with a count in the heading.

Rules:
- A phone number has 10 digits, optionally preceded by a country code `+1`/`1`. Numbers with only 7 digits (`555-1234`) are **not** phone numbers.
- A bare run of 10 digits with no separators at all (e.g. an order number `#4155551011`) is not a phone number.
- Extensions (`ext 4`) are ignored.
- An email is `local@domain` where the domain contains a dot; strip surrounding punctuation.

## Expected output

```
Phone numbers (6):
  415-555-1011
  415-555-9999
  415-555-0000
  415-555-3333
  800-420-0001
  415-555-7788
Emails (7):
  info@example-co.com
  billing@example-co.com
  alice.zhang@example-co.com
  bob_ortega@sales.example-co.com
  priya@example-co.co.uk
  press@example-co.com
  noreply@example-co.com
```

## Notes for study designers

- Deliberate traps in the data: `+1 415-555-1011` (must normalise and de-duplicate against the main line), `555-1234` (7 digits → reject), `Order #4155551011` (10 digits but no separators → reject), `ext 4` (ignore), emails wrapped in `<>` / `()` / trailing commas, a `.co.uk` domain.
- Reasonable participant strategy: scan for maximal runs of "phone-ish" characters, count digits, then reformat. Emails: split on whitespace, strip punctuation, check for a single `@` and a dot after it.
- If your tool supports `re`, the book's original regex version makes a nice "compare two solutions" condition.
- Extensions: also capture the extension as a separate field; output as CSV with columns `kind,value,line_number`; group phone numbers by area code (nested dict).

## Example solution

```python
# Extract phone numbers (normalised to NNN-NNN-NNNN) and email addresses from free text.

def digits_only(s):
    return "".join(ch for ch in s if ch.isdigit())

def find_phones(text):
    """Scan the text for runs that look like US phone numbers.

    A candidate is a maximal run of characters drawn from digits and the
    separator set " ()-.+". It counts as a phone number if it contains exactly
    10 digits (or 11 starting with a leading 1) AND at least one separator
    (so bare 10-digit codes like an order number are ignored).
    """
    allowed = set("0123456789 ()-.+")
    phones = []
    i = 0
    while i < len(text):
        if text[i] in allowed:
            j = i
            while j < len(text) and text[j] in allowed:
                j += 1
            chunk = text[i:j]
            # A run may contain several numbers separated by whitespace-only
            # gaps ("ext 4" breaks the run, but "or 415..." does not); split on
            # 2+ spaces or newlines to be safe, and then test each piece.
            for piece in chunk.replace("\n", "  ").split("  "):
                d = digits_only(piece)
                if len(d) == 11 and d[0] == "1":
                    d = d[1:]
                has_separator = any(c in piece.strip() for c in " ()-.")
                if len(d) == 10 and has_separator:
                    phones.append(f"{d[0:3]}-{d[3:6]}-{d[6:]}")
            i = j
        else:
            i += 1
    return phones

def find_emails(text):
    """An email is a maximal run of email-safe characters containing exactly one '@'
    with a '.' after it. Trailing punctuation is stripped."""
    safe = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._%+-@")
    emails = []
    for token in text.replace("<", " ").replace(">", " ").replace("(", " ").replace(")", " ").split():
        run = "".join(ch for ch in token if ch in safe).strip(".,;:")
        if run.count("@") == 1:
            local, domain = run.split("@")
            if local and "." in domain and not domain.startswith(".") and not domain.endswith("."):
                emails.append(run)
    return emails

def dedupe(items):
    seen = set()
    out = []
    for x in items:
        if x not in seen:
            seen.add(x)
            out.append(x)
    return out

with open("phone-email-extractor.input.txt") as f:
    text = f.read()

phones = dedupe(find_phones(text))
emails = dedupe(find_emails(text))

print(f"Phone numbers ({len(phones)}):")
for p in phones:
    print("  " + p)
print(f"Emails ({len(emails)}):")
for e in emails:
    print("  " + e)
```

## Regex variant (same output)

```python
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
```
