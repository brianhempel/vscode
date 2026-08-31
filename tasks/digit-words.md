# Digit words (calibration values)

- **Source:** Paraphrased from Advent of Code 2023, day 1 ("Trebuchet?!", https://adventofcode.com/2023/day/1). AoC's About page asks that puzzle text and inputs not be copied, so the description is rewritten in our own words and the 12 lines are synthetic (they exercise the same edge cases as the original: no digit characters at all, overlapping words such as `oneight`, and `sixteen` which contains `six` but not `ten`). AoC puzzles are used as a problem source in the PSB2 program-synthesis benchmark (Helmuth & Kelly, GECCO 2021) and in several LLM code-generation benchmarks. This puzzle is well known for how many people got Stage B wrong.
- **Tags:** character classification · substring detection at each index · dict lookup of word→value · list first/last · summation · formatted table output
- **Data:** `digit-words.input.txt` — 12 short lines.
- **Stdlib used in solution:** none beyond builtins
- **Difficulty:** easy (Stage A) / medium (Stage B, because of overlaps)
- **Shape:** string → list of ints → int, summed over lines, rendered as a table

## Task description (as given to participant)

Each line of `digit-words.input.txt` is a jumble of letters and digits. Each line hides a two-digit *calibration value*: the **first digit** in the line followed by the **last digit** (which may be the same character if there's only one). For example `pqr3stu8vwx` → 38 and `treb7uchet` → 77.

- **Stage A.** Compute each line's value using only digit characters (`0`–`9`). A line with no digits counts as 0. Print a table of lines and values and the sum.
- **Stage B.** Now spelled-out digits `one`, `two`, … `nine` also count as digits. So `two1nine` → 29 and `eightwothree` → 83. Be careful: words may **overlap** — `oneight` contains both `one` and `eight`, so its value is 18. Add a column for the Stage B values and their sum.

## Expected output

```
line                 A   B
1abc2               12  12
pqr3stu8vwx         38  38
a1b2c3d4e5f         15  15
treb7uchet          77  77
two1nine            11  29
eightwothree         0  83
abcone2threexyz     22  13
xtwone3four         33  24
4nineeightseven2    42  42
zoneight234         24  14
7pqrstsixteen       77  76
oneight              0  18
sum                351 441
```

## Notes for study designers

- Stage A is a one-liner-ish warm-up; Stage B is where the "detect small patterns" interest lives. The classic wrong approach is `line.replace("one", "1")` in some fixed order, which breaks overlaps (`oneight`, `twone`, `eightwo`). A tool that shows intermediate values per line should make this failure visible immediately.
- Natural stages: (1) per-character digit filter; (2) per-index `startswith` scan against a word dict; (3) first/last → number; (4) sum and format.
- Variants: ask for the values as a dict `{line: value}` or a JSON list; add `zero`; ask participants to *edit* a Stage-A script into Stage B (a genuine incremental-editing task).
- Row `eightwothree` shows a Stage A value of 0 (no digit characters) — a deliberate edge case.

## Example solution

```python
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
```
