# Top rank per group

- **Source:** Rosetta Code task "Top rank per group" (https://rosettacode.org/wiki/Top_rank_per_group); Rosetta Code content is GFDL 1.3. The description and CSV are our own (the first nine employees are the Rosetta example's fictional records, re-typed; six more were added so every department has ≥3 people and one department has a salary tie).
- **Tags:** CSV reading · group-by into dict of lists · sort by multiple keys · slice top-N · render a text table *and* nested JSON
- **Data:** `top-rank-per-group.input.csv` — 15 employees in 4 departments.
- **Stdlib used in solution:** `csv`, `json`
- **Difficulty:** easy
- **Shape:** CSV string → list of dicts → dict of lists → two string renderings (table, JSON)

## Task description (as given to participant)

`top-rank-per-group.input.csv` has columns `employee_id,name,salary,department`. Write a script that, for every department, finds the **two** highest-paid employees (ties broken by name, alphabetically) and prints:

1. a plain-text report, one block per department (departments in alphabetical order), showing rank, name and salary with thousands separators; then
2. the same information as pretty-printed JSON of the form `{"D050": [{"name": ..., "salary": ...}, ...], ...}`.

Make the "2" a single constant so it is easy to change to 3.

## Expected output

```
Department D050
  Rank Name                Salary
  1    Eva Lindqvist       47,000
  2    John Rappl          47,000
Department D101
  Rank Name                Salary
  1    George Woltman      53,500
  2    David McClellan     41,500
Department D190
  Rank Name                Salary
  1    Kim Arlich          57,000
  2    Hana Kobayashi      50,200
Department D202
  Rank Name                Salary
  1    Priya Raman         44,100
  2    Claire Buckman      27,800

{
  "D050": [
    {
      "name": "Eva Lindqvist",
      "salary": 47000
    },
    {
      "name": "John Rappl",
      "salary": 47000
    }
  ],
  "D101": [
    {
      "name": "George Woltman",
      "salary": 53500
    },
    {
      "name": "David McClellan",
      "salary": 41500
    }
  ],
  "D190": [
    {
      "name": "Kim Arlich",
      "salary": 57000
    },
    {
      "name": "Hana Kobayashi",
      "salary": 50200
    }
  ],
  "D202": [
    {
      "name": "Priya Raman",
      "salary": 44100
    },
    {
      "name": "Claire Buckman",
      "salary": 27800
    }
  ]
}
```

## Notes for study designers

- A compact, very typical "group → sort → top-N → render" pipeline. It is a good *first* task or a warm-up: the string work is light (CSV parsing via `csv.DictReader`, formatting), the data-structure work is the point.
- Natural stages: (1) load rows and convert `salary` to `int`; (2) group into `{department: [rows]}`; (3) per-group sort by `(-salary, name)`; (4) slice `[:N]`; (5) render twice.
- Gotchas: sorting salaries as strings (`"53500" < "9000"`); forgetting the tie-break (department D050 has two employees on 47,000); the `{:,}` thousands separator.
- Variants: ask for bottom-N instead; add a second grouping key (department × year); ask for the JSON output to be written to a file rather than printed.

## Example solution

```python
# Top rank per group: read an employee CSV, group by department, keep the top N earners per group.

import csv
import json

TOP_N = 2

def load(path):
    with open(path, newline="") as f:
        rows = list(csv.DictReader(f))
    for row in rows:
        row["salary"] = int(row["salary"])
    return rows

def group_by(rows, key):
    groups = {}
    for row in rows:
        groups.setdefault(row[key], []).append(row)
    return groups

def top_per_group(groups, n):
    result = {}
    for dept in sorted(groups):
        ranked = sorted(groups[dept], key=lambda r: (-r["salary"], r["name"]))
        result[dept] = [{"name": r["name"], "salary": r["salary"]} for r in ranked[:n]]
    return result

def render_table(top):
    lines = []
    for dept, people in top.items():
        lines.append(f"Department {dept}")
        lines.append(f"  {'Rank':<5}{'Name':<18}{'Salary':>8}")
        for rank, p in enumerate(people, start=1):
            lines.append(f"  {rank:<5}{p['name']:<18}{p['salary']:>8,}")
    return "\n".join(lines)

rows = load("top-rank-per-group.input.csv")
top = top_per_group(group_by(rows, "department"), TOP_N)
print(render_table(top))
print()
print(json.dumps(top, indent=2))
```
