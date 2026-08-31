# Camel case (warm-up)

- **Source:** PSB2 "Camel Case" problem (Helmuth & Kelly, GECCO 2021, https://arxiv.org/abs/2106.06086 ; https://www.cs.hamilton.edu/~thelmuth/PSB2/PSB2.html ), itself taken from the Codewars kata "Convert string to camel case" (https://www.codewars.com/kata/517abf86da9663f1d2000003).
- **Tags:** string splitting · joining · character-case manipulation · bidirectional transform
- **Data:** `camel-case.input.txt` — 6 identifiers, one per line (own examples in the style of the kata).
- **Stdlib used in solution:** none beyond builtins
- **Difficulty:** easy (5-minute warm-up)
- **Shape:** string → list of words → string, then the reverse direction

## Task description (as given to participant)

`camel-case.input.txt` contains one identifier per line written in kebab-case (`the-stealth-warrior`), snake_case (`user_id`), or a mix of both (`get-http_response-code`).

**Stage 1.** Convert each identifier to camelCase: the first word keeps its original casing, every following word is capitalised, and the separators are removed. Print `original -> camel` per line.

**Stage 2.** Convert each camelCase result *back* to kebab-case: put a `-` before every uppercase letter and lowercase everything. Print `camel -> kebab` per line.

## Expected output

```
Stage 1: to camelCase
the-stealth-warrior        -> theStealthWarrior
A-B-C                      -> ABC
user_id                    -> userId
already                    -> already
get-http_response-code     -> getHttpResponseCode
snake_case_only            -> snakeCaseOnly

Stage 2: back to kebab-case
theStealthWarrior          -> the-stealth-warrior
ABC                        -> a-b-c
userId                     -> user-id
already                    -> already
getHttpResponseCode        -> get-http-response-code
snakeCaseOnly              -> snake-case-only
```

## Notes for study designers

- Deliberately tiny; useful as the first task so participants learn the tool on something with no data-structure work.
- Stage 2 is not a true inverse (`A-B-C` → `ABC` → `a-b-c`), which is a nice discussion point / possible follow-up edit ("make the round trip lossless").
- Natural "edit" variants: handle `__double__` separators; treat digits; produce PascalCase instead.
- PSB2 ships 200 training / 2000 test cases if you want more inputs.

## Example solution

```python
# Camel case: convert kebab-case / snake_case identifiers to camelCase, and back.

def to_camel(identifier):
    # Treat both '-' and '_' as word separators.
    words = identifier.replace("_", "-").split("-")
    words = [w for w in words if w]  # drop empties from doubled separators
    if not words:
        return ""
    first, rest = words[0], words[1:]
    # First word keeps its original casing; the rest get a capital first letter.
    return first + "".join(w[0].upper() + w[1:] for w in rest)

def to_kebab(identifier):
    # Insert '-' before every uppercase letter, then lowercase everything.
    out = []
    for ch in identifier:
        if ch.isupper():
            out.append("-")
            out.append(ch.lower())
        else:
            out.append(ch)
    return "".join(out).strip("-")

with open("camel-case.input.txt") as f:
    identifiers = [line.strip() for line in f if line.strip()]

print("Stage 1: to camelCase")
camels = []
for ident in identifiers:
    camel = to_camel(ident)
    camels.append(camel)
    print(f"{ident:<26} -> {camel}")

print()
print("Stage 2: back to kebab-case")
for camel in camels:
    print(f"{camel:<26} -> {to_kebab(camel)}")
```
