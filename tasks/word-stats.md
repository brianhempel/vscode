# Word stats

- **Source:** PSB1 "Word Stats" problem — Helmuth & Spector, "General Program Synthesis Benchmark Suite", GECCO 2015, https://dl.acm.org/doi/10.1145/2739480.2754769 (the problem was adapted from an introductory programming course assignment). Also on the PSB1 site: https://thelmuth.github.io/GECCO_2015_Benchmarks_Materials/
- **Tags:** tokenising text · stripping punctuation · dict histogram · counting terminators · averaging/formatting
- **Data:** `word-stats.input.txt` — 4 lines / 8 sentences of my own text.
- **Stdlib used in solution:** none beyond builtins
- **Difficulty:** easy
- **Shape:** string → list of words → dict (histogram) → formatted report

## Task description (as given to participant)

Read `word-stats.input.txt` and print:

1. A histogram of word lengths, one line per length that occurs, in increasing order, formatted `words of length N: COUNT`. Words are whitespace-separated tokens with surrounding punctuation removed (`dog.` counts as a 3-letter word; `No,` as a 2-letter word).
2. `number of sentences: N` — a sentence ends with `.`, `?` or `!`.
3. `average sentence length: X.XX` — total words divided by number of sentences, two decimals.

## Expected output

```
words of length 1: 2
words of length 2: 5
words of length 3: 18
words of length 4: 14
words of length 5: 7
words of length 6: 4
words of length 7: 2
words of length 8: 2
number of sentences: 8
average sentence length: 6.75
```

## Notes for study designers

- Three distinct sub-goals in one script, each a natural checkpoint for the study.
- The "strip punctuation from words" step is where people usually go wrong first (`hedge.` vs `hedge`), and the two definitions of "word" vs "sentence terminator" interact — good for observing how participants debug.
- Extensions: also print the longest word, or ignore stop-words, or emit the histogram as JSON.
- The original PSB1 problem prints exactly these three items; the punctuation set is not fully specified in PSB1, so the task text above fixes it.

## Example solution

```python
# Word stats: word-length histogram, sentence count, average sentence length.

SENTENCE_ENDS = ".?!"

def words_of(text):
    # Split on whitespace, then strip punctuation from both ends of each token.
    result = []
    for token in text.split():
        word = token.strip(".,!?;:\"'()")
        if word:
            result.append(word)
    return result

def count_sentences(text):
    # A sentence ends at '.', '?' or '!'. A trailing fragment without a
    # terminator (if any) is not counted.
    return sum(1 for ch in text if ch in SENTENCE_ENDS)

with open("word-stats.input.txt") as f:
    text = f.read()

words = words_of(text)
histogram = {}
for w in words:
    histogram[len(w)] = histogram.get(len(w), 0) + 1

for length in sorted(histogram):
    print(f"words of length {length}: {histogram[length]}")

sentences = count_sentences(text)
print(f"number of sentences: {sentences}")
print(f"average sentence length: {len(words) / sentences:.2f}")
```
