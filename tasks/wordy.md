# Wordy (math word problems)

- **Source:** Exercism `wordy` exercise — https://github.com/exercism/problem-specifications/tree/main/exercises/wordy (MIT).
- **Tags:** parsing natural-language-ish strings · two-word tokens (`multiplied by`) · left-to-right evaluation · error classification · map over lines
- **Data:** `wordy.input.txt` — 12 questions, one per line (the Exercism canonical cases; the error lines are the spec's own).
- **Stdlib used in solution:** none beyond builtins
- **Difficulty:** medium
- **Shape:** string → token list → number, with structured error handling

## Task description (as given to participant)

Each line of `wordy.input.txt` is a question such as `What is 5 plus 13?`. Write a script that prints `question -> answer` for each line.

- Supported operations: `plus`, `minus`, `multiplied by`, `divided by` (integer division). Numbers may be negative.
- Evaluate strictly left to right, ignoring the usual precedence: `What is 3 plus 2 multiplied by 3?` is `(3 + 2) * 3 = 15`.
- A question with an operation you don't support (`What is 52 cubed?`) or that isn't a math question at all should print `-> ERROR: unknown operation`.
- A malformed question (`What is 1 plus?`, `What is 1 plus plus 2?`, `What is 1 plus 2 1?`) should print `-> ERROR: syntax error`.

## Expected output

```
What is 5? -> 5
What is 5 plus 13? -> 18
What is 7 minus 5? -> 2
What is 6 multiplied by 4? -> 24
What is 25 divided by 5? -> 5
What is 3 plus 2 multiplied by 3? -> 15
What is -3 plus 7 multiplied by -2? -> -8
What is 52 cubed? -> ERROR: unknown operation
Who is the President of the United States? -> ERROR: unknown operation
What is 1 plus? -> ERROR: syntax error
What is 1 plus plus 2? -> ERROR: syntax error
What is 1 plus 2 1? -> ERROR: syntax error
```

## Notes for study designers

- Not a data-processing task: it is a tiny interpreter. The interesting design decision is how to turn `multiplied by` into one token (the solution does a replace-then-split; participants might instead scan two tokens at a time).
- The distinction between "unknown operation" and "syntax error" makes a good second-stage edit: start with a version that raises one generic error and ask participants to classify.
- Extension: add `raised to the Nth power` (`What is 2 raised to the 5th power?`), which needs ordinal-suffix stripping — another small pattern.
- Exercism's canonical data has ~25 cases; the 12 here cover all of them structurally.

## Example solution

```python
# Wordy: evaluate simple math word problems, left to right.

OPERATIONS = {
    "plus": lambda a, b: a + b,
    "minus": lambda a, b: a - b,
    "multiplied by": lambda a, b: a * b,
    "divided by": lambda a, b: a // b,
}

def tokenize(question):
    # Strip the fixed prefix/suffix, then turn two-word operators into one token.
    if not question.startswith("What is") or not question.endswith("?"):
        raise ValueError("unknown operation")
    body = question[len("What is"):-1].strip()
    body = body.replace("multiplied by", "multiplied_by").replace("divided by", "divided_by")
    return [tok.replace("_", " ") for tok in body.split()]

def is_number(tok):
    return tok.lstrip("-").isdigit()

def answer(question):
    tokens = tokenize(question)
    if not tokens:
        raise ValueError("syntax error")
    # Expect: number (op number)*
    if not is_number(tokens[0]):
        raise ValueError("unknown operation" if tokens[0] not in OPERATIONS else "syntax error")
    result = int(tokens[0])
    i = 1
    while i < len(tokens):
        op = tokens[i]
        if is_number(op):
            raise ValueError("syntax error")       # two numbers in a row
        if op not in OPERATIONS:
            raise ValueError("unknown operation")  # e.g. "cubed"
        if i + 1 >= len(tokens) or not is_number(tokens[i + 1]):
            raise ValueError("syntax error")       # dangling / doubled operator
        result = OPERATIONS[op](result, int(tokens[i + 1]))
        i += 2
    return result

with open("wordy.input.txt") as f:
    for line in f:
        q = line.strip()
        if not q:
            continue
        try:
            print(f"{q} -> {answer(q)}")
        except ValueError as e:
            print(f"{q} -> ERROR: {e}")
```
