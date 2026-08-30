# Natural sort: order filenames so that img2 < img10 < img100, case-insensitively.

def chunks(s):
    """Split 'img10-v2.png' into ['img', 10, '-v', 2, '.png'] — digit runs become ints."""
    parts = []
    current = ""
    for ch in s:
        if current and ch.isdigit() != current[-1].isdigit():
            parts.append(current)
            current = ""
        current += ch
    if current:
        parts.append(current)
    return [int(p) if p.isdigit() else p.lower() for p in parts]

def natural_key(s):
    # Every key must compare int-with-int and str-with-str at each position, so tag
    # each chunk with its type: (0, int) sorts before (1, str) when they would otherwise clash.
    return [(0, c) if isinstance(c, int) else (1, c) for c in chunks(s)]

if __name__ == "__main__":
    with open("natural-sort.input.txt") as f:
        names = [line.strip() for line in f if line.strip()]

    plain = sorted(names)
    natural = sorted(names, key=natural_key)
    print(f"{'Plain sorted()':<16} {'Natural sort'}")
    for a, b in zip(plain, natural):
        print(f"{a:<16} {b}")
