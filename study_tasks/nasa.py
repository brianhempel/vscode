import random

with open('nasa-log.txt', 'r') as f:
    lines = f.readlines()

    N = 30

    # Remove lines until there are only N left
    while len(lines) > N:
        lines.pop(random.randint(0, len(lines) - 1))

    # Write the remaining lines
    with open('nasa-log-n.txt', 'w') as f:
        for line in lines:
            f.write(line)
