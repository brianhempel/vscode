# Crypto square

- **Source:** Exercism `crypto-square` exercise — https://github.com/exercism/problem-specifications/tree/main/exercises/crypto-square (MIT). A classic columnar-transposition cipher.
- **Tags:** normalising strings (lowercase, drop non-alphanumerics) · chunking into rows · transposing a grid of characters · padding · joining chunks · decoding (inverse transform)
- **Data:** `crypto-square.input.txt` — 3 plaintext lines (the examples from the Exercism spec).
- **Stdlib used in solution:** `math`
- **Difficulty:** medium
- **Shape:** string → list of rows (grid) → string, and back again

## Task description (as given to participant)

For each line of `crypto-square.input.txt`:

**Stage 1 — encode.**
1. Normalise: lowercase and remove everything that is not a letter or digit.
2. Choose a rectangle with `r` rows and `c` columns such that `c >= r`, `c - r <= 1`, and `r * c >= len(text)` (smallest such rectangle). Write the text into it row by row, padding the last row with spaces.
3. Read the rectangle column by column. Output the columns as space-separated chunks — every chunk has length `r`, so the padded chunks end with spaces.

Example: `"If man was meant to stay on the ground, god would have given us roots."` normalises to 54 characters, fits an 7×8 rectangle, and encodes as `imtgdvs fearwer mayoogo anouuio ntnnlvt wttddes aohghn  sseoau ` (note the two trailing-space paddings).

**Stage 2 — decode.** Take the ciphertext you produced and recover the normalised plaintext.

Print `plain:`, `cipher:` and `decoded:` lines for each input line, followed by a blank line.

## Expected output

(Ciphertext lines end in trailing spaces where padding occurred; e.g. the first `cipher:` line ends `aohghn  sseoau ` with a space after `sseoau`.)

```
plain:   If man was meant to stay on the ground, god would have given us roots.
cipher:  imtgdvs fearwer mayoogo anouuio ntnnlvt wttddes aohghn  sseoau 
decoded: ifmanwasmeanttostayonthegroundgodwouldhavegivenusroots

plain:   Chill out.
cipher:  clu hlt io 
decoded: chillout

plain:   Vampires are people too!
cipher:  vrel aepe mset paoo irpo
decoded: vampiresarepeopletoo

```

## Notes for study designers

- Goes string → grid → string and then the reverse, which is exactly the "back and forth" shape requested.
- Realistic pitfall that the example solution hit on its first attempt: the decoder cannot simply `split(" ")` because padding spaces sit *inside* chunks. Handing participants a buggy decoder of that shape is a ready-made edit task.
- The rectangle-size rule is a small arithmetic sub-problem participants can solve by trial (`for c in range(...)`) or with `sqrt`.
- Exercism canonical data has 8 cases including the empty string.

## Example solution

```python
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

if __name__ == "__main__":
    with open("crypto-square.input.txt") as f:
        for line in f:
            line = line.rstrip("\n")
            cipher = encode(line)
            print(f"plain:   {line}")
            print(f"cipher:  {cipher}")
            print(f"decoded: {decode(cipher)}")
            print()
```
