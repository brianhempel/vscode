# Pig Latin

- **Source:** Exercism `pig-latin` exercise — https://github.com/exercism/problem-specifications/tree/main/exercises/pig-latin (MIT); the same problem (with simpler rules) is PSB1 "Pig Latin" (Helmuth & Spector, GECCO 2015, https://dl.acm.org/doi/10.1145/2739480.2754769 ).
- **Tags:** small-pattern detection at the start of a word (`qu`, `xr`, `yt`, consonant clusters) · string slicing · map over words · preserving line structure
- **Data:** `pig-latin.input.txt` — 5 lines, 17 words, chosen to hit every rule in the Exercism spec (words from that spec's test cases).
- **Stdlib used in solution:** none beyond builtins
- **Difficulty:** medium (the rules interact)
- **Shape:** text → lines → words → transformed words → text

## Task description (as given to participant)

Translate each line of `pig-latin.input.txt` into Pig Latin, word by word, and print `original -> translated`. All words are lowercase letters only. Rules:

1. If a word begins with a vowel (`a e i o u`), or with `xr` or `yt`, add `ay` to the end: `apple → appleay`, `xray → xrayay`.
2. Otherwise move the leading consonant cluster to the end and add `ay`: `chair → airchay`, `therapy → erapythay`.
3. `qu` counts as part of the consonant cluster even when the `q` is preceded by other consonants: `quick → ickquay`, `square → aresquay`.
4. A `y` that follows at least one consonant is treated as a vowel: `my → ymay`, `rhythm → ythmrhay`. A `y` at the very start of a word is a consonant: `yellow → ellowyay`.

## Expected output

```
quick fast run                   -> ickquay astfay unray
apple ear igloo object under     -> appleay earay iglooay objectay underay
xray yttria xylophone            -> xrayay yttriaay ylophonexay
chair square therapy             -> airchay aresquay erapythay
my rhythm yellow                 -> ymay ythmrhay ellowyay
```

## Notes for study designers

- Almost no data-structure work; the challenge is entirely small-pattern detection at word boundaries, with four rules that must be checked in the right order.
- Good "edit" scenario: give participants a version that implements rules 1–2 only and ask them to add rules 3 and 4 (each is a one-or-two-line change in the right place).
- Every input word appears in Exercism's canonical test data, so the expected output is authoritative.
- Extension: preserve capitalisation and trailing punctuation (`Hello, world!`).

## Example solution

```python
# Pig Latin translator following the Exercism rule set.

VOWELS = "aeiou"

def translate_word(word):
    # Rule 1: starts with a vowel sound (vowel, or "xr"/"yt") -> just add "ay".
    if word[0] in VOWELS or word.startswith("xr") or word.startswith("yt"):
        return word + "ay"

    # Otherwise find the end of the leading consonant cluster.
    i = 0
    while i < len(word):
        ch = word[i]
        if ch in VOWELS:
            break
        # Rule 4: "y" after at least one consonant acts as a vowel.
        if ch == "y" and i > 0:
            break
        # Rule 3: "qu" is moved together (the "u" belongs to the cluster).
        if ch == "q" and i + 1 < len(word) and word[i + 1] == "u":
            i += 2
            break
        i += 1
    return word[i:] + word[:i] + "ay"

def translate_line(line):
    return " ".join(translate_word(w) for w in line.split())

with open("pig-latin.input.txt") as f:
    for line in f:
        line = line.rstrip("\n")
        print(f"{line:<32} -> {translate_line(line)}")
```
