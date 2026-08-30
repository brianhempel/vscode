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

if __name__ == "__main__":
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
