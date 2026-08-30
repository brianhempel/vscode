# For each (day, time) slot, pick the session with the most "award or
# crowdsourcing" papers, joining sessions.json to papers.json on paper ID.
import json

with open("chi15.papers.json") as f:
    papers = {p["ID"]: p for p in json.load(f)}
with open("chi15.sessions.json") as f:
    sessions = json.load(f)

def interesting(paper):
    return paper["award"] in ("bp", "hm") or "crowdsourcing" in paper["keywords"]

# slot -> list of (count, session, qualifying titles)
slots = {}
for s in sessions:
    good = [papers[pid]["paper_title"] for pid in s["submissions"] if interesting(papers[pid])]
    slots.setdefault((s["day"], s["time"]), []).append((len(good), s, good))

DAY_ORDER = ["Monday", "Tuesday", "Wednesday", "Thursday"]
current_day = None
for (day, time) in sorted(slots, key=lambda k: (DAY_ORDER.index(k[0]), k[1])):
    if day != current_day:
        print(f"== {day}")
        current_day = day
    count, best, titles = max(slots[(day, time)], key=lambda t: t[0])
    print(f"  {time}  {best['session_title']} ({best['room']}) -- {count} award/crowdsourcing paper(s)")
    for t in titles:
        print(f"      * {t}")
