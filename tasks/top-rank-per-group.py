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
