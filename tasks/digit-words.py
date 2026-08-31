# Digit words: recover a two-digit number from the first and last digit hidden in each line.

WORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
         "six": 6, "seven": 7, "eight": 8, "nine": 9}

def digits_only(line):
    return [int(ch) for ch in line if ch.isdigit()]

def digits_and_words(line):
    """Scan every position; a digit char or a spelled-out word starting there counts.
    Overlaps like 'oneight' yield both 1 and 8 because we never skip ahead."""
    found = []
    for i, ch in enumerate(line):
        if ch.isdigit():
            found.append(int(ch))
            continue
        for word, value in WORDS.items():
            if line.startswith(word, i):
                found.append(value)
                break
    return found

def calibration(line, extractor):
    ds = extractor(line)
    if not ds:
        return 0
    return ds[0] * 10 + ds[-1]

with open("digit-words.input.txt") as f:
    lines = [line.strip() for line in f if line.strip()]
print(f"{'line':<18}{'A':>4}{'B':>4}")
total_a = total_b = 0
for line in lines:
    a = calibration(line, digits_only)
    b = calibration(line, digits_and_words)
    total_a += a
    total_b += b
    print(f"{line:<18}{a:>4}{b:>4}")
print(f"{'sum':<18}{total_a:>4}{total_b:>4}")
