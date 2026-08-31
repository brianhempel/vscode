# Range extraction and expansion

- **Source:** Rosetta Code tasks "Range extraction" (https://rosettacode.org/wiki/Range_extraction) and "Range expansion" (https://rosettacode.org/wiki/Range_expansion); Rosetta Code content is GFDL 1.3. Description and input are our own; the first `extract` case and the first `expand` case mirror the canonical Rosetta examples. The compact `1-3,5,7-9` format is the one used by printers' page-range dialogs and by `cut`/`sed`/`nice` on Unix, which is what makes the task feel real.
- **Tags:** list → string (run detection) · string → list (parsing with a tricky delimiter) · negative numbers · line-prefix dispatch
- **Data:** `range-extraction.input.txt` — 7 lines, each prefixed `extract:` or `expand:`.
- **Stdlib used in solution:** none beyond builtins
- **Difficulty:** easy–medium
- **Shape:** goes in *both* directions: list of ints ⇄ compact range string

## Task description (as given to participant)

Page-range strings like `0-2,4,6-8,11` are a compact way to write a sorted list of integers. Each line in `range-extraction.input.txt` asks for one of two conversions:

- `extract: <comma-separated integers>` — turn the (sorted, distinct) integers into the compact form. Only **three or more** consecutive integers become a range `a-b`; a run of two stays as two separate numbers. So `0, 1, 2, 4, 6, 7, 8, 11` → `0-2,4,6-8,11`.
- `expand: <compact string>` — do the reverse, producing the full list of integers.

Negative numbers are allowed, which makes the dash ambiguous: `-6--3` means "from −6 to −3", and `-3-1` means "from −3 to 1". (Rule: a `-` in the first position is a sign; the first `-` after that is the range separator.)

Print, for each line, the input and the converted result.

## Expected output

```
extract  0, 1, 2, 4, 6, 7, 8, 11, 12, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24, 25, 27, 28, 29, 30, 31, 32, 33, 35, 36, 37, 38, 39
      -> 0-2,4,6-8,11,12,14-25,27-33,35-39
extract  -6, -3, -2, -1, 0, 1, 3, 4, 5, 7, 8, 10, 11, 14, 15, 17, 18, 19, 20
      -> -6,-3-1,3-5,7,8,10,11,14,15,17-20
extract  1, 2, 4, 5, 7, 8
      -> 1,2,4,5,7,8
extract  42
      -> 42
expand   -6,-3--1,3-5,7-11,14,15,17-20
      -> [-6, -3, -2, -1, 3, 4, 5, 7, 8, 9, 10, 11, 14, 15, 17, 18, 19, 20]
expand   0-2,4,6-8,11,12,14-25,27-33,35-39
      -> [0, 1, 2, 4, 6, 7, 8, 11, 12, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24, 25, 27, 28, 29, 30, 31, 32, 33, 35, 36, 37, 38, 39]
expand   5
      -> [5]
```

## Notes for study designers

- A small, self-contained task where the *same* data goes list→string and string→list, so participants must think about the round trip. It is not a "process a data set" task.
- Natural stages: (1) dispatch on the line prefix; (2) `extract`: find runs of consecutive values with an index loop, emit `a-b` for runs ≥ 3; (3) `expand`: split on `,`, then split each piece on the *separator* dash (not a sign dash), `range(lo, hi + 1)`.
- Gotchas: the 3-or-more rule; the `-3-1` / `-6--3` parsing; whitespace after commas in the `extract` input.
- Variants: require that `expand(extract(xs)) == xs` and print a check; extend to unsorted input (sort + dedupe first); output the ranges as a list of `(lo, hi)` tuples instead of a string.

## Example solution

```python
# Range extraction / expansion: convert between integer lists and compact "a-b,c" range strings.

def extract(numbers):
    """[0, 1, 2, 4, 6, 7, 8, 11] -> '0-2,4,6-8,11' (ranges only for 3+ consecutive values)."""
    pieces = []
    i = 0
    while i < len(numbers):
        j = i
        while j + 1 < len(numbers) and numbers[j + 1] == numbers[j] + 1:
            j += 1
        run = numbers[i:j + 1]
        if len(run) >= 3:
            pieces.append(f"{run[0]}-{run[-1]}")
        else:
            pieces.extend(str(n) for n in run)
        i = j + 1
    return ",".join(pieces)

def split_range(piece):
    """'3-5' -> (3, 5); '-6--3' -> (-6, -3); '7' -> (7, 7). A '-' after position 0 is the separator."""
    sep = piece.find("-", 1)
    if sep == -1:
        n = int(piece)
        return n, n
    return int(piece[:sep]), int(piece[sep + 1:])

def expand(text):
    """'-6,-3--1,3-5' -> [-6, -3, -2, -1, 3, 4, 5]"""
    result = []
    for piece in text.split(","):
        lo, hi = split_range(piece.strip())
        result.extend(range(lo, hi + 1))
    return result

with open("range-extraction.input.txt") as f:
    for line in f:
        line = line.strip()
        if not line:
            continue
        mode, payload = line.split(":", 1)
        payload = payload.strip()
        if mode == "extract":
            numbers = [int(x) for x in payload.split(",")]
            print(f"extract  {payload}")
            print(f"      -> {extract(numbers)}")
        elif mode == "expand":
            print(f"expand   {payload}")
            print(f"      -> {expand(payload)}")
        else:
            raise ValueError(f"unknown mode {mode!r}")
```
