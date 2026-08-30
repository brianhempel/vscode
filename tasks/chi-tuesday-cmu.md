# CHI'15 Tuesday papers from CMU

- **Source:** Kerry Shih-Ping Chang, *Using Web Services and Creating Interactive Web Applications in Spreadsheet Programs* (Gneiss), PhD thesis, CMU HCII, ch. 5 §5.5.4 user study; published as Chang & Myers, "Using and Exploring Hierarchical Data in Spreadsheets", CHI 2016 — https://doi.org/10.1145/2858036.2858506 . In that between-subjects study 12 spreadsheet users (Gneiss vs. Excel) and 6 programmers (JavaScript/Python in Sublime) did five tasks on two JSON files from CHI'15: `papers.json` (484 papers: `ID`, `paper_title`, `abstract`, `keywords[]`, `type` long/short, `award` none/bp/hm, `authors[{name, institution, city, country}]`) and `sessions.json` (119 sessions: `session_title`, `room`, `day`, `time`, `chair`, `submissions[]` of paper IDs). Participants rated the tasks highly realistic (6.56/7). Programmers took roughly 5–12 minutes per task. Our data is **synthetic** in exactly that shape (invented titles and author names; real institution names).
- **Tags:** JSON · filter · join on ID list · any() over a nested list · sort
- **Data:** `chi15.papers.json` (14 papers) and `chi15.sessions.json` (6 sessions) — shared by all four `chi-*` tasks.
- **Stdlib used in solution:** `json`
- **Difficulty:** easy
- **Shape:** two nested JSON files → filtered join → text

## Task description (as given to participant)

Using `chi15.sessions.json` and `chi15.papers.json`, list every paper that is presented on **Tuesday** and has at least one author from **Carnegie Mellon University**. Print the count, then one line per paper with the session time, session title and paper title, sorted by time.

## Expected output

```
Tuesday papers with a Carnegie Mellon University author: 1
  09:00-10:20  [End-User Programming]  Debugging Spreadsheets with Live Previews
```

## Notes for study designers

- Study task 4. Mechanically the easiest of the join tasks (filter sessions → look up papers → `any()` over authors), but it needs both files and both a scalar filter (`day`) and a nested-list filter (`authors`). Good as the first cross-file task in a session.
- Only one paper qualifies in the synthetic data; swap a session's day to make it two.
- Extension: take the day and institution from `sys.argv`; match institution case-insensitively / by substring (`"Carnegie Mellon"`).

## Example solution

```python
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
```
