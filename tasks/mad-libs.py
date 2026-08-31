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

with open("mad-libs.input.txt") as f:
    template = f.read()
words = load_words("mad-libs.words.txt")

text, counts = fill(template, words)
print(text)
print()
print("Replaced:", ", ".join(f"{k}={counts[k]}" for k in PLACEHOLDERS))
unused = sum(len(words[k]) - counts[k] for k in PLACEHOLDERS)
print(f"Unused words: {unused}")
