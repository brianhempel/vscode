# Crypto square cipher: normalize, lay out in a near-square, read down columns.
import math

def normalize(text):
    return "".join(ch.lower() for ch in text if ch.isalnum())

def dimensions(n):
    # Smallest c with c >= r, c - r <= 1 and r * c >= n.
    c = math.ceil(math.sqrt(n))
    r = math.ceil(n / c) if c else 0
    return r, c

def encode(text):
    plain = normalize(text)
    if not plain:
        return ""
    r, c = dimensions(len(plain))
    rows = [plain[i:i + c].ljust(c) for i in range(0, len(plain), c)]
    # Read column by column; each column becomes one output chunk.
    chunks = ["".join(row[j] for row in rows) for j in range(c)]
    return " ".join(chunks)

def decode(cipher):
    if not cipher:
        return ""
    # Chunks all have length r and are separated by single spaces. The padding
    # spaces live at the *end* of later chunks, so we cannot simply split on
    # spaces; instead take r from the first chunk (which is never padded).
    r = cipher.index(" ") if " " in cipher else len(cipher)
    chunks = [cipher[i:i + r] for i in range(0, len(cipher), r + 1)]
    rows = ["".join(chunk[i] for chunk in chunks) for i in range(r)]
    return "".join(rows).rstrip()

with open("crypto-square.input.txt") as f:
    for line in f:
        line = line.rstrip("\n")
        cipher = encode(line)
        print(f"plain:   {line}")
        print(f"cipher:  {cipher}")
        print(f"decoded: {decode(cipher)}")
        print()
