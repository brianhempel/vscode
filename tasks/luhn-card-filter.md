# Luhn card-number filter

- **Source:** PSB2 "Luhn" problem (Helmuth & Kelly, GECCO 2021, https://arxiv.org/abs/2106.06086 ; https://www.cs.hamilton.edu/~thelmuth/PSB2/PSB2.html ) and the Exercism `luhn` exercise — https://github.com/exercism/problem-specifications/tree/main/exercises/luhn (MIT). The Luhn algorithm itself is the real check-digit scheme used on credit-card numbers.
- **Tags:** string cleaning (remove spaces) · character validation · digit arithmetic · filtering a list · masking/formatting
- **Data:** `luhn-card-filter.input.txt` — 11 candidate numbers, one per line (test-suite style examples from the Exercism canonical data plus well-known test card numbers).
- **Stdlib used in solution:** none beyond builtins
- **Difficulty:** easy–medium
- **Shape:** list of strings → validated/filtered list → reformatted strings

## Task description (as given to participant)

Each line of `luhn-card-filter.input.txt` is a candidate card number. Digits may be grouped with spaces; some lines contain other characters or are too short.

A number is valid under the Luhn check if:
- after removing spaces it consists only of digits and is longer than one digit;
- doubling every second digit from the right (subtracting 9 from any result over 9) and summing all digits gives a total divisible by 10.

**Stage 1.** Print each candidate followed by `VALID` or `INVALID`.

**Stage 2.** Print how many are valid, then list the valid ones masked as `**** **** **** ` followed by their last four digits.

## Expected output

```
4539 3195 0343 6467    VALID
8273 1232 7352 0569    INVALID
0                      INVALID
059                    VALID
055 444 285            VALID
055a 444 285           INVALID
4111 1111 1111 1111    VALID
5105 1051 0510 5100    VALID
1234 5678 9012 3456    INVALID
3782 822463 10005      VALID
6011-1111-1111-1117    INVALID

6 valid number(s):
  **** **** **** 6467
  **** **** **** 059
  **** **** **** 4285
  **** **** **** 1111
  **** **** **** 5100
  **** **** **** 0005
```

## Notes for study designers

- Small-pattern detection: "spaces allowed, nothing else"; the `6011-1111-…` line with hyphens is INVALID under the spec — a natural follow-up edit is "also accept hyphens".
- `059` passes Luhn but is only three digits; the masking then shows `**** **** **** 059`. Another follow-up: "only accept 13–19-digit numbers" or "mask only the last four".
- The core loop is a classic off-by-one trap (which digits get doubled) — good for observing debugging.
- Exercism's `canonical-data.json` for `luhn` has ~20 labelled cases if you want a test set.

## Example solution

```python
# Luhn check: validate candidate card numbers, then list valid ones masked.

def luhn_valid(candidate):
    digits = candidate.replace(" ", "")
    # Must be all digits and longer than one digit.
    if len(digits) <= 1 or not digits.isdigit():
        return False
    total = 0
    # Walk from the right; double every second digit.
    for i, ch in enumerate(reversed(digits)):
        d = int(ch)
        if i % 2 == 1:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return total % 10 == 0

def mask(candidate):
    digits = candidate.replace(" ", "")
    return "**** **** **** " + digits[-4:]

if __name__ == "__main__":
    with open("luhn-card-filter.input.txt") as f:
        candidates = [line.rstrip("\n") for line in f if line.strip()]

    valid = []
    for c in candidates:
        ok = luhn_valid(c)
        print(f"{c:<22} {'VALID' if ok else 'INVALID'}")
        if ok:
            valid.append(c)

    print()
    print(f"{len(valid)} valid number(s):")
    for c in valid:
        print(f"  {mask(c)}")
```
