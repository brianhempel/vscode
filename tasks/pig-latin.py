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
