# OCR numbers

- **Source:** Exercism `ocr-numbers` exercise — https://github.com/exercism/problem-specifications/tree/main/exercises/ocr-numbers (MIT). Adapted from the "Bank OCR" kata at codingdojo.org (http://codingdojo.org/kata/BankOCR/), a widely used coding-dojo exercise.
- **Tags:** 2-D text grids · slicing fixed-width columns · building a lookup key from several lines · dict lookup with a default · grouping lines in fours · joining results
- **Data:** `ocr-numbers.input.txt` — 16 lines = 4 groups of 4 lines (own rendering of the spec's glyphs; the 4th group deliberately contains a garbled digit).
- **Stdlib used in solution:** none beyond builtins
- **Difficulty:** medium
- **Shape:** text → list of 4-line groups → per-column string keys → dict lookup → strings

## Task description (as given to participant)

`ocr-numbers.input.txt` contains numbers "printed" with pipes and underscores. Each digit is 3 characters wide and 4 lines tall (the 4th line is always blank), like this:

```
    _  _     _  _  _  _  _ 
  | _| _||_||_ |_   ||_||_|
  ||_  _|  | _||_|  ||_| _|
                           
```
(that is `123456789`; zero is ` _ `, `| |`, `|_|`).

The file holds several such 4-line groups one after another. Write a script that:

1. splits the file into groups of 4 lines;
2. for each group, splits it into 3-character-wide glyphs and recognises each glyph as a digit, using `?` for anything unrecognised;
3. prints `group N: <digits>` per group, then `joined:` with all groups joined by commas.

Lines may be shorter than a multiple of 3 (trailing spaces trimmed); treat missing characters as spaces.

## Expected output

```
group 1: 1234567890
group 2: 123
group 3: 456
group 4: 12?
joined: 1234567890,123,456,12?
```

## Notes for study designers

- Pure small-pattern detection over a 2-D string grid, with no numeric computation. The key design step is choosing a representation for a glyph (the solution flattens the 4×3 block into a 12-character string used as a dict key).
- Realistic wrinkle: editors strip trailing whitespace, so short lines must be padded — a plausible bug for an "edit this failing script" variant.
- Exercism's spec adds validation errors (line count not a multiple of 4, width not a multiple of 3); those make good extension stages.
- Extension: also support reading the digits *back out* — render a digit string as glyphs (the inverse transform).

## Example solution

```python
# OCR numbers: recognise 3x4 pipe/underscore glyphs, one group of 4 lines at a time.

GLYPHS = {
    " _ | ||_|   ": "0",
    "     |  |   ": "1",
    " _  _||_    ": "2",
    " _  _| _|   ": "3",
    "   |_|  |   ": "4",
    " _ |_  _|   ": "5",
    " _ |_ |_|   ": "6",
    " _   |  |   ": "7",
    " _ |_||_|   ": "8",
    " _ |_| _|   ": "9",
}

def read_group(lines):
    # lines: exactly 4 strings. Pad each to a multiple of 3 characters.
    width = max(len(l) for l in lines)
    width += (-width) % 3
    lines = [l.ljust(width) for l in lines]
    digits = []
    for col in range(0, width, 3):
        # A glyph is the 4 rows x 3 columns block, flattened row by row.
        key = "".join(l[col:col + 3] for l in lines)
        digits.append(GLYPHS.get(key, "?"))
    return "".join(digits)

def read_file(path):
    with open(path) as f:
        raw = [line.rstrip("\n") for line in f]
    groups = [raw[i:i + 4] for i in range(0, len(raw), 4)]
    return [read_group(g) for g in groups if len(g) == 4]

results = read_file("ocr-numbers.input.txt")
for i, r in enumerate(results, 1):
    print(f"group {i}: {r}")
print("joined:", ",".join(results))
```
