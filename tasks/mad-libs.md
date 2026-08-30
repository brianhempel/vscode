# Mad Libs

- **Source:** *Automate the Boring Stuff with Python* (Al Sweigart), 2nd ed., Chapter 8 practice project "Mad Libs" — https://automatetheboringstuff.com/2e/chapter8/ . The book reads the template from a file and prompts the user for each word; this variant reads the words from a second file so it runs non-interactively. Template and word list are our own.
- **Tags:** text generation · tokenisation · placeholder substitution · per-category queues · punctuation handling
- **Data:** `mad-libs.input.txt` (4-line template), `mad-libs.words.txt` (10 lines, `KIND: word`).
- **Stdlib used in solution:** none beyond builtins
- **Difficulty:** easy–medium
- **Shape:** two text files → dict of lists → generated text (not a data-processing task)

## Task description (as given to participant)

`mad-libs.input.txt` is a short story in which some words have been replaced by the placeholders `ADJECTIVE`, `NOUN`, `VERB` and `ADVERB`. Placeholders may be followed by punctuation (`VERB.`) or preceded by a quote (`"ADJECTIVE`).

`mad-libs.words.txt` lists replacement words, one per line, as `KIND: word`, e.g. `NOUN: chandelier`. Words of each kind should be used **in the order they appear in the file**.

Write a script that prints the story with every placeholder replaced by the next unused word of that kind, keeping all punctuation and line breaks intact. Then print a line counting how many placeholders of each kind were replaced, and the number of words in the word file that were never used.

## Expected output

```
The silly panda walked to the chandelier and then screamed.
A nearby pickup truck was unaffected by these events, though it did look suspiciously
at the purple clouds. "That was enormous," said the teapot, and it began to
sing loudly.

Replaced: ADJECTIVE=3, NOUN=3, VERB=2, ADVERB=2
Unused words: 0
```

## Notes for study designers

- This is a generation task rather than a data-processing one: the "data structure" is a dict of per-kind queues built from the word file, then consumed while walking the template's tokens.
- The gotchas are all string-level: `VERB.` and `"ADJECTIVE` must still be recognised (strip trailing punctuation / leading quote, then re-attach), and multi-word replacements like `pickup truck` must be inserted verbatim.
- Good "edit the script" follow-ups: (a) add a new kind `PLURAL_NOUN`; (b) if a kind runs out, fall back to the placeholder in lowercase; (c) make the replacement match the case of the placeholder (`Noun` → capitalised).
- Simpler variant: use `str.replace` for each kind (the book's approach), which fails to keep per-kind ordering — a nice conversation starter about why a token walk is needed.

## Example solution

```python
# Mad Libs: fill ADJECTIVE/NOUN/VERB/ADVERB placeholders from a word list, in order.

PLACEHOLDERS = ("ADJECTIVE", "NOUN", "VERB", "ADVERB")

def load_words(path):
    """Return {"NOUN": ["chandelier", "pickup truck"], ...} keeping file order."""
    words = {p: [] for p in PLACEHOLDERS}
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            kind, word = line.split(":", 1)
            words[kind.strip().upper()].append(word.strip())
    return words

def split_word(token):
    """Split 'VERB.' into ('VERB', '.') so punctuation glued to a placeholder survives."""
    core = token.rstrip('.,!?;:"')
    return core, token[len(core):]

def fill(template, words):
    """Replace placeholders token by token. Returns (text, counts)."""
    counts = {p: 0 for p in PLACEHOLDERS}
    queues = {p: list(ws) for p, ws in words.items()}  # copies we can pop from
    out_lines = []
    for line in template.splitlines():
        out_tokens = []
        for token in line.split(" "):
            core, tail = split_word(token)
            lead = core[: len(core) - len(core.lstrip('"('))]  # leading quote/paren
            key = core[len(lead):]
            if key in PLACEHOLDERS and queues[key]:
                out_tokens.append(lead + queues[key].pop(0) + tail)
                counts[key] += 1
            else:
                out_tokens.append(token)
        out_lines.append(" ".join(out_tokens))
    return "\n".join(out_lines), counts

if __name__ == "__main__":
    with open("mad-libs.input.txt") as f:
        template = f.read()
    words = load_words("mad-libs.words.txt")

    text, counts = fill(template, words)
    print(text)
    print()
    print("Replaced:", ", ".join(f"{k}={counts[k]}" for k in PLACEHOLDERS))
    unused = sum(len(words[k]) - counts[k] for k in PLACEHOLDERS)
    print(f"Unused words: {unused}")
```
