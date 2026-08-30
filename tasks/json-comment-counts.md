# JSON comment counts

- **Source:** *Python for Everybody* (Charles Severance), Chapter 13 assignment "Extracting Data from JSON" — https://www.py4e.com/ ; the course's sample data lives at http://py4e-data.dr-chuck.net/comments_42.json and has exactly this shape (`{"note": …, "comments": [{"name": …, "count": …}, …]}`). Names/counts here are our own small synthetic set in the same format.
- **Tags:** JSON loading · list of dicts · sum/sort/slice · grouping into dict-of-dicts · string formatting
- **Data:** `json-comment-counts.input.json` — 20 records.
- **Stdlib used in solution:** `json`
- **Difficulty:** easy
- **Shape:** JSON → list of dicts → grouped nested dict → formatted report

## Task description (as given to participant)

`json-comment-counts.input.json` looks like this:

```json
{
  "note": "This file contains the sample data for testing",
  "comments": [
    {"name": "Romina", "count": 97},
    {"name": "Laurie", "count": 97},
    ...
  ]
}
```

Write a script that loads the file and prints:

1. the `note`, the number of commenters, and the sum of all `count` values;
2. the top three commenters by count (ties broken alphabetically), name padded to 10 characters;
3. a summary grouped by the first letter of the name: for each letter (sorted), the total count for that group, right-aligned to width 3, followed by the alphabetically sorted names in parentheses.

## Expected output

```
Note: This file contains the sample data for testing
Number of commenters: 20
Total count: 1227
Top 3:
  Laurie     97
  Romina     97
  Bayli      90
By initial:
  A: 247 (Ameelia, Amrit, Ana, Asif)
  B: 133 (Bayli, Bethany)
  C: 112 (Cassie, Cody)
  D:  67 (Danyil)
  L: 120 (Lachlann, Laurie, Layla)
  P:  76 (Prasheeta)
  R: 205 (Risa, Romina, Ruby)
  S: 113 (Siyabonga, Sonny)
  T:  85 (Taisha)
  Z:  69 (Zi)
```

## Notes for study designers

- The course version only asks for the sum (part 1); parts 2–3 add sorting with a compound key and a group-by step so that participants build a nested structure and then render it.
- URL variant (as in the course): replace the `open()` with `urllib.request.urlopen("http://py4e-data.dr-chuck.net/comments_42.json").read()` and `json.loads(...)` — that file has 50 entries, which is still small. The course also provides a per-student URL (`comments_<id>.json`) so each participant can get a different dataset.
- Gotcha for part 2: sorting by `-count` then name; participants often get the tie order wrong (Romina vs Laurie).
- Extension: invert the grouping to `{count_bucket: [names]}` (e.g. buckets of 10), or write the summary back out as JSON.

## Example solution

```python
# JSON comment counts: total, top-3 commenters, and a per-initial summary.
import json

with open("json-comment-counts.input.json") as f:
    data = json.load(f)

comments = data["comments"]
print(f"Note: {data['note']}")
print(f"Number of commenters: {len(comments)}")
print(f"Total count: {sum(c['count'] for c in comments)}")

print("Top 3:")
for c in sorted(comments, key=lambda c: (-c["count"], c["name"]))[:3]:
    print(f"  {c['name']:<10} {c['count']}")

# Group by first letter of the name -> {"letter": {"names": [...], "total": n}}
groups = {}
for c in comments:
    letter = c["name"][0].upper()
    g = groups.setdefault(letter, {"names": [], "total": 0})
    g["names"].append(c["name"])
    g["total"] += c["count"]

print("By initial:")
for letter in sorted(groups):
    g = groups[letter]
    print(f"  {letter}: {g['total']:>3} ({', '.join(sorted(g['names']))})")
```
