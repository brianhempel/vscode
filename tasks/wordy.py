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
