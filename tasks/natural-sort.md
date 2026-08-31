# Natural sort of filenames

- **Source:** Stack Overflow, "How to correctly sort a string with a number inside?" — https://stackoverflow.com/questions/5967500/how-to-correctly-sort-a-string-with-a-number-inside (a canonical, highly-viewed question; the accepted answer uses `re.split` to build a key). Filenames here are our own.
- **Tags:** run-length tokenisation (digit vs non-digit) · sort keys · mixed-type comparison · case-insensitivity
- **Data:** `natural-sort.input.txt` — 14 filenames.
- **Stdlib used in solution:** none beyond builtins
- **Difficulty:** easy
- **Shape:** list of strings → list of mixed str/int chunks → sorted list

## Task description (as given to participant)

`natural-sort.input.txt` contains one filename per line, e.g. `img12.png`, `img2.png`, `IMG1.png`, `img2-final.png`, `img10-v10.png`. Python's default `sorted()` puts `img10.png` before `img2.png` because it compares character by character.

Write a script that prints the filenames in "natural" order — where runs of digits are compared numerically (`img2` < `img10` < `img100`), letters are compared case-insensitively, and a name whose digits are followed by more text sorts next to its base name (`img2-final.png` next to `img2.png`). Print the plain and natural orders side by side in two columns (first column padded to 16 characters).

## Expected output

```
Plain sorted()   Natural sort
IMG1.png         IMG1.png
Img3.png         img1.png
img.png          img2-draft.png
img02.png        img2-final.png
img1.png         img2.png
img10-v10.png    img02.png
img10-v2.png     Img3.png
img10.png        img10-v2.png
img100.png       img10-v10.png
img12.png        img10.png
img2-draft.png   img12.png
img2-final.png   img100.png
img2.png         img.png
photo.png        photo.png
```

## Notes for study designers

- Small but instructive: the whole task is "split a string into alternating digit/non-digit runs" (pattern detection) followed by building a compound sort key (data structure). Without `re`, participants write a short scanner loop.
- Gotcha: Python 3 refuses to compare `int` with `str`, which bites when two names differ in *type* at the same chunk position (e.g. `img.png` vs `img1.png`). The solution tags chunks with a type code; alternative is padding digit runs with zeros into a pure-string key.
- Edge cases in the data: `img02.png` vs `img2.png` (equal numeric value — order should be stable), `IMG1.png` vs `img1.png` (case), `img.png` (no number), `img10-v10.png` vs `img10-v2.png` (second number).
- Extension: sort a directory listing from `os.listdir` this way, or sort version strings (`1.10.0` after `1.9.0`) — see `semver-constraints` for the full version-comparison task.

## Example solution

```python
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

with open("natural-sort.input.txt") as f:
    names = [line.strip() for line in f if line.strip()]

plain = sorted(names)
natural = sorted(names, key=natural_key)
print(f"{'Plain sorted()':<16} {'Natural sort'}")
for a, b in zip(plain, natural):
    print(f"{a:<16} {b}")
```
