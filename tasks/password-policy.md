# Password policy checker

- **Source:** Paraphrased from Advent of Code 2020, day 2 ("Password Philosophy") — https://adventofcode.com/2020/day/2. AoC asks that puzzle text and inputs not be copied, so the description here is our own wording and `password-policy.input.txt` is a small synthetic input we generated. AoC puzzles are an established source for program-synthesis and LLM benchmarks (e.g. several PSB2 problems come from AoC), which supports ecological validity.
- **Tags:** line parsing (split on `: `, ` `, `-`) · list of dicts · `str.count` · 1-indexed positions · filtering with two predicates
- **Data:** `password-policy.input.txt` — 15 lines.
- **Stdlib used in solution:** none beyond builtins
- **Difficulty:** easy (~10 minutes)
- **Shape:** string lines → list of dicts → filtered lists → summary strings

## Task description (as given to participant)

Each line of `password-policy.input.txt` is a password together with the policy it was supposed to follow when it was created:

```
1-3 a: abcde
1-3 b: cdefg
2-9 c: ccccccccc
```

Two different administrators disagree about what the policy `1-3 a` means:

- **Rule A:** the letter `a` must appear **between 1 and 3 times** (inclusive) in the password.
- **Rule B:** **exactly one** of positions 1 and 3 (1-indexed, no notion of "index zero") must contain the letter `a`.

Write a script that parses every line into its parts (low, high, letter, password), then prints:

1. the total number of entries,
2. how many passwords are valid under rule A,
3. how many are valid under rule B,
4. the list of passwords valid under rule B, each with its policy.

## Expected output

```
Total entries: 15
Valid under rule A (count in range): 10
Valid under rule B (exactly one position): 4
Rule B passwords:
  abcde  (1-3 a)
  kkkabc  (3-5 k)
  attempt  (1-3 t)
  pineapple  (1-4 p)
```

## Notes for study designers

- Natural stages: (1) multi-step split of each line into a small record; (2) one predicate per rule; (3) filter and count; (4) format output.
- Rule B exercises "exactly one of" (XOR) and 1- vs 0-indexed positions — both common sources of small bugs, and good targets for an "edit the script" condition (e.g. give participants a version that uses `or` instead of `!=`, or forgets the `- 1`).
- Extensions: read a third rule from the user; emit a CSV with a `valid_a,valid_b` column per entry; report which entries are valid under *both* rules (`attempt`, `abcde` …).
- A regex (`(\d+)-(\d+) (\w): (\w+)`) is the "obvious" parse for many programmers; the string-split version is shown to avoid `re`.

## Example solution

```python
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
```
