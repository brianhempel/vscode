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
