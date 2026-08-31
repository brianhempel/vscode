# Kindergarten garden

- **Source:** Exercism `kindergarten-garden` exercise — https://github.com/exercism/problem-specifications/tree/main/exercises/kindergarten-garden (problem-specifications repo, MIT licence). A long-standing exercise on Exercism's Python and many other tracks.
- **Tags:** string slicing · fixed-width "grid" parsing · index arithmetic · dict of lists · string joining
- **Data:** `kindergarten-garden.input.txt` — 2 lines of 24 plant codes each (the full-garden example from the spec).
- **Stdlib used in solution:** none beyond builtins
- **Difficulty:** easy (~10 minutes)
- **Shape:** string grid → per-child list → string

## Task description (as given to participant)

A kindergarten class has a window-sill garden laid out as two rows of cups. Each cup holds one plant, encoded by a letter:

- `V` = violets, `R` = radishes, `C` = clover, `G` = grass

The file `kindergarten-garden.input.txt` contains the two rows, e.g.

```
VRCGVVRVCGGCCGVRGCVCGCGV
VRCCCGCRRGVCGCRVVCVGCGCV
```

There are 12 children, and they are assigned cups in **alphabetical order** of their names:

Alice, Bob, Charlie, David, Eve, Fred, Ginny, Harriet, Ileana, Joseph, Kincaid, Larry.

Each child gets the **two adjacent cups** at their position in the front row and the same two in the back row (so Alice has the first two cups of each row, Bob the next two, and so on).

Write a script that prints one line per child, in alphabetical order, listing the four plants they own (front row first, then back row), like:

```
Alice: violets, radishes, violets, radishes
Bob: clover, grass, clover, clover
```

## Expected output

```
Alice: violets, radishes, violets, radishes
Bob: clover, grass, clover, clover
Charlie: violets, violets, clover, grass
David: radishes, violets, clover, radishes
Eve: clover, grass, radishes, grass
Fred: grass, clover, violets, clover
Ginny: clover, grass, grass, clover
Harriet: violets, radishes, radishes, violets
Ileana: grass, clover, violets, clover
Joseph: violets, clover, violets, grass
Kincaid: grass, clover, clover, grass
Larry: grass, violets, clover, violets
```

## Notes for study designers

- Natural stages: (1) read the two rows; (2) compute the slice `row[2*i : 2*i+2]` for each child; (3) map letters to plant names via a dict; (4) join into the output line.
- The main "pattern detection" element is the fixed-width 2-cup chunking of each row — a simple but real index-arithmetic step.
- Good "edit this script" variants: change the number of cups per child, add a third row, accept an explicit list of children from a second file (the Exercism spec's later test cases do this), or output a JSON object instead of text lines.
- Gotcha: children must be sorted alphabetically even if listed out of order — the spec's later test cases supply names unsorted.

## Example solution

```python
# Kindergarten garden: two rows of plant codes -> which plants each child owns.

PLANTS = {"V": "violets", "R": "radishes", "C": "clover", "G": "grass"}

CHILDREN = [
    "Alice", "Bob", "Charlie", "David", "Eve", "Fred",
    "Ginny", "Harriet", "Ileana", "Joseph", "Kincaid", "Larry",
]

def parse_garden(text):
    rows = [line.strip() for line in text.splitlines() if line.strip()]
    return rows

def plants_for(rows, index):
    """Child at position `index` gets cups 2*index and 2*index+1 in every row."""
    start = 2 * index
    codes = []
    for row in rows:
        codes.extend(row[start:start + 2])
    return [PLANTS[c] for c in codes]

def assign(rows):
    garden = {}
    for i, child in enumerate(sorted(CHILDREN)):
        garden[child] = plants_for(rows, i)
    return garden

with open("kindergarten-garden.input.txt") as f:
    rows = parse_garden(f.read())
garden = assign(rows)
for child, plants in garden.items():
    print(f"{child}: {', '.join(plants)}")
```
