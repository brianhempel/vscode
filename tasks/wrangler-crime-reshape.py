# Wrangler task 1: turn "Reported crime in <State>" blocks into tidy state,year,rate rows.

HEADER_PREFIX = "Reported crime in "

def parse_blocks(lines):
    """Return a list of (state, year, rate) tuples."""
    rows = []
    state = None
    for line in lines:
        line = line.strip()
        if not line:
            continue
        if line.startswith(HEADER_PREFIX):
            state = line[len(HEADER_PREFIX):]
        else:
            year, rate = line.split(",")
            rows.append((state, int(year), float(rate)))
    return rows

with open("wrangler-crime-reshape.input.txt") as f:
    rows = parse_blocks(f)

print("state,year,rate")
for state, year, rate in rows:
    print(f"{state},{year},{rate}")

# Group into {state: {year: rate}} and report each state's peak year.
by_state = {}
for state, year, rate in rows:
    by_state.setdefault(state, {})[year] = rate

print()
print("Peak year per state:")
for state in sorted(by_state):
    years = by_state[state]
    peak = max(years, key=years.get)
    print(f"  {state:<10} {peak} ({years[peak]})")
