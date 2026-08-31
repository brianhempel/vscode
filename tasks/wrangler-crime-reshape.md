# Crime data: reshape block-structured text into a tidy table

- **Source:** Sean Kandel, Andreas Paepcke, Joseph Hellerstein, Jeffrey Heer, "Wrangler: Interactive Visual Specification of Data Transformation Scripts", CHI 2011 — http://vis.stanford.edu/files/2011-Wrangler-CHI.pdf . This is the paper's user-study **Task 1**: a text export of US state crime rates in which each state's block is introduced by a line `Reported crime in <State>` followed by `year,rate` lines, which participants had to reshape into a tidy `state,year,rate` table. The values here are **synthetic** (four states × five years) in the same layout; the original used FBI Uniform Crime Reports data for all 50 states.
- **Tags:** block-structured text · prefix detection · carrying context across lines · tidy/long table output · group-by + max
- **Data:** `wrangler-crime-reshape.input.txt` — 4 state blocks, 30 lines including blanks.
- **Stdlib used in solution:** none beyond builtins
- **Difficulty:** easy
- **Shape:** semi-structured text → list of tuples → CSV text, then → dict-of-dicts → summary

## Task description (as given to participant)

`wrangler-crime-reshape.input.txt` is an export from a statistics website. Each state's data is a block like

```
Reported crime in Alabama

2004,4029.3
2005,3900.0
...
```

with blank lines between blocks. Write a script that:

1. prints the data as a tidy CSV with header `state,year,rate` — one row per state/year (blank lines dropped, state name taken from the block header);
2. prints, for each state in alphabetical order, the year with the highest rate and that rate, as `  State      YEAR (rate)` with the state name padded to 10 characters.

## Expected output

```
state,year,rate
Alabama,2004,4029.3
Alabama,2005,3900.0
Alabama,2006,3937.0
Alabama,2007,3974.9
Alabama,2008,4081.9
Alaska,2004,3370.9
Alaska,2005,3615.0
Alaska,2006,3582.0
Alaska,2007,3373.9
Alaska,2008,2928.3
Arizona,2004,5073.3
Arizona,2005,4827.0
Arizona,2006,4741.6
Arizona,2007,4502.6
Arizona,2008,4087.3
Arkansas,2004,4085.8
Arkansas,2005,4148.5
Arkansas,2006,4076.2
Arkansas,2007,3979.0
Arkansas,2008,3894.4

Peak year per state:
  Alabama    2008 (4081.9)
  Alaska     2005 (3615.0)
  Arizona    2004 (5073.3)
  Arkansas   2005 (4148.5)
```

## Notes for study designers

- This is a *state-machine over lines* task: the state name found on a header line must be remembered and attached to subsequent rows ("fill down" in Wrangler terms). The pattern to detect is the `Reported crime in ` prefix; everything else is `year,rate`.
- It was designed and timed as a user-study task in the Wrangler paper (participants took a few minutes in Excel), so it is an ecologically valid "data wrangling" task of known difficulty.
- Extensions faithful to the original data: some blocks have a trailing "Note: …" line to skip; rates written with thousands separators (`4,029.3`) so the naive `split(",")` breaks; write to a CSV file with the `csv` module; add a per-year national average (transpose the grouping).
- Pairs naturally with `wrangler-housing-crosstab` (the paper's Task 2).

## Example solution

```python
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
```
