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
