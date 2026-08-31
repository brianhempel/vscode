# Password policy: parse "lo-hi letter: password" lines and validate under two rules.

def parse(line):
    policy, password = line.strip().split(": ")
    rng, letter = policy.split(" ")
    lo, hi = rng.split("-")
    return {"lo": int(lo), "hi": int(hi), "letter": letter, "password": password}

def valid_by_count(entry):
    n = entry["password"].count(entry["letter"])
    return entry["lo"] <= n <= entry["hi"]

def valid_by_position(entry):
    pw, letter = entry["password"], entry["letter"]
    first = pw[entry["lo"] - 1] == letter    # positions are 1-indexed
    second = pw[entry["hi"] - 1] == letter
    return first != second                   # exactly one of them

with open("password-policy.input.txt") as f:
    entries = [parse(line) for line in f if line.strip()]

by_count = [e for e in entries if valid_by_count(e)]
by_position = [e for e in entries if valid_by_position(e)]

print(f"Total entries: {len(entries)}")
print(f"Valid under rule A (count in range): {len(by_count)}")
print(f"Valid under rule B (exactly one position): {len(by_position)}")
print("Rule B passwords:")
for e in by_position:
    print(f"  {e['password']}  ({e['lo']}-{e['hi']} {e['letter']})")
