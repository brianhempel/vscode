# Stage 1: authors with more than one paper in the SAME session.
# Stage 2: authors with papers in DIFFERENT sessions in the same time slot
#          (a real scheduling conflict).
import json

with open("chi15.papers.json") as f:
    papers = {p["ID"]: p for p in json.load(f)}
with open("chi15.sessions.json") as f:
    sessions = json.load(f)

# author -> list of (day, time, session_title, paper_title)
appearances = {}
for s in sessions:
    for pid in s["submissions"]:
        for a in papers[pid]["authors"]:
            appearances.setdefault(a["name"], []).append(
                (s["day"], s["time"], s["session_title"], papers[pid]["paper_title"]))

print("Stage 1: two or more papers in the same session")
for author in sorted(appearances):
    by_session = {}
    for day, time, session, title in appearances[author]:
        by_session.setdefault((day, time, session), []).append(title)
    for (day, time, session), titles in by_session.items():
        if len(titles) > 1:
            print(f"  {author} -- {session} ({day} {time}): " + " / ".join(titles))

print()
print("Stage 2: papers in different sessions in the same time slot")
for author in sorted(appearances):
    by_slot = {}
    for day, time, session, title in appearances[author]:
        by_slot.setdefault((day, time), set()).add(session)
    for (day, time), names in by_slot.items():
        if len(names) > 1:
            print(f"  {author} -- {day} {time}: " + " vs ".join(sorted(names)))
