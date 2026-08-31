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

with open("etl-scrabble.input.json") as f:
    old = json.load(f)

new = transform(old)
print("Stage 1: letter -> score")
print(json.dumps(new))

print()
print("Stage 2: word scores")
for word in ["cabbage", "quiz", "python", "oxyphenbutazone"]:
    print(f"{word:<16} {score_word(word, new)}")
