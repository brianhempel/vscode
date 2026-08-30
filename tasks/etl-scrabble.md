# ETL: invert a Scrabble score table

- **Source:** Exercism `etl` exercise — https://github.com/exercism/problem-specifications/tree/main/exercises/etl (MIT). Framed there as a real-world "extract–transform–load" migration of a legacy data format.
- **Tags:** JSON in/out · inverting a dict-of-lists into a flat dict · lowercasing keys · sorting keys · using the result to score strings
- **Data:** `etl-scrabble.input.json` — the standard English Scrabble letter scores in the legacy `score -> [letters]` layout (7 keys, 26 letters).
- **Stdlib used in solution:** `json`
- **Difficulty:** easy
- **Shape:** nested JSON (dict of lists) → flat dict → used to map over strings

## Task description (as given to participant)

The legacy file `etl-scrabble.input.json` stores Scrabble letter scores as `{"1": ["A", "E", ...], "2": ["D", "G"], ...}` — score first, then the list of (uppercase) letters with that score.

**Stage 1.** Convert it to the new layout: one key per lowercase letter mapping to its integer score, keys in alphabetical order. Print it as a single line of JSON.

**Stage 2.** Using the new table, print the Scrabble score for the words `cabbage`, `quiz`, `python` and `oxyphenbutazone` (one per line, word left-aligned to 16 characters).

## Expected output

```
Stage 1: letter -> score
{"a": 1, "b": 3, "c": 3, "d": 2, "e": 1, "f": 4, "g": 2, "h": 4, "i": 1, "j": 8, "k": 5, "l": 1, "m": 3, "n": 1, "o": 1, "p": 3, "q": 10, "r": 1, "s": 1, "t": 1, "u": 1, "v": 4, "w": 4, "x": 8, "y": 4, "z": 10}

Stage 2: word scores
cabbage          14
quiz             22
python           14
oxyphenbutazone  41
```

## Notes for study designers

- Very small, but it is a genuine nested → flat inversion, and the JSON keys being *strings* (`"10"`) is a realistic wrinkle (sort order, `int()` conversion).
- Stage 2 turns the data structure back around to act on strings.
- Extensions: write the result to a file; add a check that every letter a–z is present exactly once; handle a word with a letter not in the table.

## Example solution

```python
# ETL: transform score -> [LETTERS] into letter -> score, then score some words.
import json

def transform(old):
    new = {}
    for score, letters in old.items():
        for letter in letters:
            new[letter.lower()] = int(score)
    return dict(sorted(new.items()))

def score_word(word, scores):
    return sum(scores[ch] for ch in word.lower() if ch in scores)

if __name__ == "__main__":
    with open("etl-scrabble.input.json") as f:
        old = json.load(f)

    new = transform(old)
    print("Stage 1: letter -> score")
    print(json.dumps(new))

    print()
    print("Stage 2: word scores")
    for word in ["cabbage", "quiz", "python", "oxyphenbutazone"]:
        print(f"{word:<16} {score_word(word, new)}")
```
