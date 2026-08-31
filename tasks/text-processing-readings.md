# Text processing: daily sensor readings

- **Source:** Rosetta Code "Text processing/1" — https://rosettacode.org/wiki/Text_processing/1 (task text CC BY-SA/GFDL). The original task was derived from a real data-quality-checking job on a 5,000-line instrument log; Rosetta Code carries ~50 language solutions, so it is a well-trodden, ecologically grounded task.
- **Tags:** tab-separated parsing · pairing alternate fields · filtering by flag · running statistics · tracking a run across lines
- **Data:** `text-processing-readings.input.txt` — 12 lines. Each line is a date followed by **6** tab-separated (value, flag) pairs (the original has 24 pairs/hourly; trimmed to 6 to keep it small). Flag ≥ 1 = good reading; flag ≤ 0 = bad. Values are synthetic; bad-flag positions were placed by hand so that one bad run spans three days.
- **Stdlib used in solution:** none beyond builtins
- **Difficulty:** medium
- **Shape:** string → list of (value, flag) tuples → per-line and cross-line aggregation → formatted report

## Task description (as given to participant)

The file `text-processing-readings.input.txt` holds one line per day. Each line is a date (`YYYY-MM-DD`), then a sequence of readings, each reading being **two** tab-separated fields: a floating-point value and an integer status flag. A flag of 1 or more means the reading is good; 0 or negative means the instrument was faulty and the value should be ignored.

Write a script that:

1. For each line prints the date, the number of good readings and the mean of the good readings (mean 0.000 if there are none).
2. Prints the total number of readings, total number of good readings and the overall mean of all good readings.
3. Finds the **longest run of consecutive bad readings** in the whole file (runs may continue across line boundaries, in file order) and prints its length and the date of the line on which it ends.

## Expected output

```
1991-03-30:  6 good readings, mean  13.748
1991-03-31:  6 good readings, mean   9.988
1991-04-01:  4 good readings, mean  18.893
1991-04-02:  6 good readings, mean  18.103
1991-04-03:  3 good readings, mean   9.754
1991-04-04:  0 good readings, mean   0.000
1991-04-05:  4 good readings, mean  15.329
1991-04-06:  6 good readings, mean  20.468
1991-04-07:  6 good readings, mean  18.712
1991-04-08:  5 good readings, mean  14.607
1991-04-09:  6 good readings, mean  19.646
1991-04-10:  6 good readings, mean  20.354

Total readings : 72
Good readings  : 58
Overall mean   : 16.643
Longest bad run: 11 readings, ending on 1991-04-05
```

## Notes for study designers

- The "pairing" step (turning a flat list of 12 fields into 6 tuples) is a good small data-structure manipulation; `zip(rest[::2], rest[1::2])` or a stride loop are both fine.
- The cross-line run is the part most people get wrong first (resetting the counter per line). A good "edit" sub-task: give a version that only finds per-line runs and ask them to fix it.
- Variants: report which *hours* are bad most often (needs the index); write results as CSV; handle a line with the wrong number of fields.
- The original Rosetta Code file (`readings.txt`) is ~5,000 lines; do **not** use it as-is.

## Example solution

```python
# Text processing/1: per-day stats over (value, flag) reading pairs, and the
# longest run of bad readings (flag <= 0) across the whole file.

def parse_line(line):
    fields = line.rstrip("\n").split("\t")
    date = fields[0]
    rest = fields[1:]
    # rest alternates value, flag, value, flag, ...
    pairs = [(float(rest[i]), int(rest[i + 1])) for i in range(0, len(rest), 2)]
    return date, pairs

with open("text-processing-readings.input.txt") as f:
    lines = [l for l in f if l.strip()]

total_good = 0
total_sum = 0.0
total_readings = 0

current_run = 0          # length of the bad run we're inside right now
best_run = 0
best_run_end = None      # date on which the best run ended

for line in lines:
    date, pairs = parse_line(line)
    good = [v for v, flag in pairs if flag >= 1]
    total_readings += len(pairs)
    total_good += len(good)
    total_sum += sum(good)
    mean = sum(good) / len(good) if good else 0.0
    print(f"{date}: {len(good):2d} good readings, mean {mean:7.3f}")

    for _, flag in pairs:
        if flag >= 1:
            current_run = 0
        else:
            current_run += 1
            if current_run > best_run:
                best_run = current_run
                best_run_end = date

print()
print(f"Total readings : {total_readings}")
print(f"Good readings  : {total_good}")
print(f"Overall mean   : {total_sum / total_good:.3f}")
print(f"Longest bad run: {best_run} readings, ending on {best_run_end}")
```
