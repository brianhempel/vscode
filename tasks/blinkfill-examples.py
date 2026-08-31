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

with open("blinkfill-examples.input.csv", newline="") as f:
    rows = list(csv.DictReader(f))
out = csv.writer(sys.stdout)
out.writerow(["country", "initials", "code", "extracted"])
for r in rows:
    out.writerow([country(r["city_country"]), initials(r["name"]),
                  close_bracket(r["code"]), between(r["message"])])
