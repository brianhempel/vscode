# Room checksums

- **Source:** Paraphrased from Advent of Code 2016, day 4 ("Security Through Obscurity", https://adventofcode.com/2016/day/4). AoC's About page asks that puzzle text and inputs not be copied, so the description is rewritten in our own words and the 14 room lines are synthetic (we encrypted our own made-up room names). AoC puzzles are used as a problem source in the PSB2 program-synthesis benchmark (Helmuth & Kelly, GECCO 2021) and in several LLM code-generation benchmarks.
- **Tags:** string splitting (`rsplit`, bracket stripping) · letter-frequency counting · multi-key sorting · filtering · Caesar-shift string transform
- **Data:** `room-checksums.input.txt` — 14 lines; 12 real rooms and 2 with bad checksums.
- **Stdlib used in solution:** `collections.Counter` (easily replaced by a dict)
- **Difficulty:** medium
- **Shape:** string → tuple/dict → filter → string

## Task description (as given to participant)

Each line of `room-checksums.input.txt` is an encrypted room label like

```
aaaaa-bbb-z-y-x-123[abxyz]
```

made of a dash-separated encrypted name (`aaaaa-bbb-z-y-x`), a numeric sector id (`123`) and a checksum in square brackets (`abxyz`).

A room is **real** if its checksum equals the five most common letters of the encrypted name (dashes don't count), ordered by frequency, with ties broken alphabetically. In the example above, `a` appears 5 times, `b` 3 times, and `x`, `y`, `z` once each, so the checksum `abxyz` is correct.

Write a script that:

1. Parses each line into name, sector id, and checksum.
2. Reports how many rooms are real, which names were rejected, and the sum of the sector ids of the real rooms.
3. Decrypts each real room's name by shifting every letter forward through the alphabet by the sector id (wrapping `z` → `a`), turning dashes into spaces, and prints the sector id and decrypted name of every real room, marking the one whose name contains `northpole`.

## Expected output

```
Real rooms: 12 of 14; rejected: ['totally-real-room', 'not-a-real-room']
Sum of real sector ids: 6884

Decrypted names:
   343  northpole object storage   <-- here
   987  very encrypted name
   512  candy cane depot
   128  reindeer stables
   987  z a b c d e f g
   275  toy workshop
   419  elf dormitory
   123  ttttt uuu s r q
   601  gift wrapping
   733  sleigh hangar
   859  cookie kitchen
   917  naughty list archive
```

## Notes for study designers

- Natural stages: (1) split the line into its three parts — a small pattern with two different delimiters (`[`, `]`, last `-`); (2) count letters; (3) sort by `(-count, letter)`; (4) filter; (5) shift cipher.
- Gotchas: `rsplit("-", 1)` vs `split("-")` for the sector id; the tie-break order; shifting by `sector % 26`; remembering dashes → spaces.
- Good "edit an existing script" variant: give participants a version whose sort ignores the alphabetical tie-break (it will accept/reject the wrong rooms) and ask them to fix it.
- Two of the synthetic rooms decrypt to nonsense (`z a b c d e f g`, `ttttt uuu s r q`) because their plaintext was chosen for checksum edge cases, not meaning; that is fine and mirrors the original puzzle.

## Example solution

```python
# Room checksums: validate encrypted room names, sum sector ids, then decrypt the real ones.

from collections import Counter

def parse(line):
    """'aaaaa-bbb-z-y-x-123[abxyz]' -> ('aaaaa-bbb-z-y-x', 123, 'abxyz')"""
    body, checksum = line.strip().rstrip("]").split("[")
    name, sector = body.rsplit("-", 1)
    return name, int(sector), checksum

def expected_checksum(name):
    counts = Counter(name.replace("-", ""))
    # Most common first; ties broken alphabetically.
    ranked = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    return "".join(letter for letter, _ in ranked[:5])

def decrypt(name, shift):
    out = []
    for ch in name:
        if ch == "-":
            out.append(" ")
        else:
            out.append(chr((ord(ch) - ord("a") + shift) % 26 + ord("a")))
    return "".join(out)

with open("room-checksums.input.txt") as f:
    rooms = [parse(line) for line in f if line.strip()]

real = [(name, sector) for name, sector, chk in rooms if expected_checksum(name) == chk]
fake = [name for name, sector, chk in rooms if expected_checksum(name) != chk]
print(f"Real rooms: {len(real)} of {len(rooms)}; rejected: {fake}")
print(f"Sum of real sector ids: {sum(sector for _, sector in real)}")
print()
print("Decrypted names:")
for name, sector in real:
    plain = decrypt(name, sector)
    marker = "   <-- here" if "northpole" in plain else ""
    print(f"  {sector:>4}  {plain}{marker}")
```
