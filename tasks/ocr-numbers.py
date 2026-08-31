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
