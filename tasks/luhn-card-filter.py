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
