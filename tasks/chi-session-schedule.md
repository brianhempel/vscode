# CHI'15 personal schedule

- **Source:** Kerry Shih-Ping Chang, *Using Web Services and Creating Interactive Web Applications in Spreadsheet Programs* (Gneiss), PhD thesis, CMU HCII, ch. 5 §5.5.4 user study; published as Chang & Myers, "Using and Exploring Hierarchical Data in Spreadsheets", CHI 2016 — https://doi.org/10.1145/2858036.2858506 . In that between-subjects study 12 spreadsheet users (Gneiss vs. Excel) and 6 programmers (JavaScript/Python in Sublime) did five tasks on two JSON files from CHI'15: `papers.json` (484 papers: `ID`, `paper_title`, `abstract`, `keywords[]`, `type` long/short, `award` none/bp/hm, `authors[{name, institution, city, country}]`) and `sessions.json` (119 sessions: `session_title`, `room`, `day`, `time`, `chair`, `submissions[]` of paper IDs). Participants rated the tasks highly realistic (6.56/7). Programmers took roughly 5–12 minutes per task. Our data is **synthetic** in exactly that shape (invented titles and author names; real institution names).
- **Tags:** JSON · join two files on an ID list · group by (day, time) · max per group · weekday ordering · grouped text report
- **Data:** `chi15.papers.json` (14 papers) and `chi15.sessions.json` (6 sessions) — shared by all four `chi-*` tasks.
- **Stdlib used in solution:** `json`
- **Difficulty:** medium (~15 min)
- **Shape:** two nested JSON files → joined records → grouped dict → text schedule

## Task description (as given to participant)

`chi15.sessions.json` lists sessions (`day`, `time`, `room`, `session_title`, `submissions` = list of paper IDs). `chi15.papers.json` has the papers (`ID`, `award` = `"none"`/`"bp"`/`"hm"`, `keywords`). Several sessions run in parallel in the same `(day, time)` slot.

Build a personal schedule: for every time slot, choose the session with the most *interesting* papers, where a paper is interesting if it won an award (`bp` or `hm`) **or** has `"crowdsourcing"` among its keywords. Print the schedule grouped by day (Monday first), one line per slot with the session title, room and count, then the interesting paper titles indented below it.

## Expected output

```
== Monday
  11:00-12:20  Crowdsourcing I (Room 301) -- 3 award/crowdsourcing paper(s)
      * Crowd-Powered Captioning for Live Lectures
      * Crowdsourcing Map Corrections in Rural Areas
      * Paying the Crowd Fairly: Wage Estimation on Microtask Platforms
== Tuesday
  09:00-10:20  Wearables & Health (Room 301) -- 1 award/crowdsourcing paper(s)
      * Wearables for Social Anxiety
  14:00-15:20  Accessibility & Aging (Room 302) -- 1 award/crowdsourcing paper(s)
      * Designing Voice Assistants for Older Adults
== Wednesday
  11:00-12:20  Learning & Play (Room 301) -- 0 award/crowdsourcing paper(s)
```

## Notes for study designers

- Study task 3 (and the §5.2 scenario, which is where the "award **or** crowdsourcing" predicate comes from). Requires a join across the two files via the `submissions` ID list, then group-by slot, then a max per group — the same three moves Gneiss users did with drag-and-drop join, "Group by", and sort/filter.
- Gotchas: days must be ordered by weekday not alphabetically; a slot with zero interesting papers still needs a pick; ties (none in this data) need a documented rule.
- Extensions: also print the room changes needed between consecutive slots; let the keyword list come from the command line.

## Example solution

```python
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
```
