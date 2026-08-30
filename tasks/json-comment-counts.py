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
