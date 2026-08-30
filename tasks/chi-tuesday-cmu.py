# Papers presented on Tuesday that have at least one author from
# Carnegie Mellon University.
import json

with open("chi15.papers.json") as f:
    papers = {p["ID"]: p for p in json.load(f)}
with open("chi15.sessions.json") as f:
    sessions = json.load(f)

TARGET = "Carnegie Mellon University"
hits = []
for s in sessions:
    if s["day"] != "Tuesday":
        continue
    for pid in s["submissions"]:
        p = papers[pid]
        if any(a["institution"] == TARGET for a in p["authors"]):
            hits.append((s["time"], s["session_title"], p["paper_title"]))

print(f"Tuesday papers with a {TARGET} author: {len(hits)}")
for time, session, title in sorted(hits):
    print(f"  {time}  [{session}]  {title}")
