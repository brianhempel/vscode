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
