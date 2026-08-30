# CHI'15 papers: keyword count and top institutions

- **Source:** Kerry Shih-Ping Chang, *Using Web Services and Creating Interactive Web Applications in Spreadsheet Programs* (Gneiss), PhD thesis, CMU HCII, ch. 5 §5.5.4 user study; published as Chang & Myers, "Using and Exploring Hierarchical Data in Spreadsheets", CHI 2016 — https://doi.org/10.1145/2858036.2858506 . In that between-subjects study 12 spreadsheet users (Gneiss vs. Excel) and 6 programmers (JavaScript/Python in Sublime) did five tasks on two JSON files from CHI'15: `papers.json` (484 papers: `ID`, `paper_title`, `abstract`, `keywords[]`, `type` long/short, `award` none/bp/hm, `authors[{name, institution, city, country}]`) and `sessions.json` (119 sessions: `session_title`, `room`, `day`, `time`, `chair`, `submissions[]` of paper IDs). Participants rated the tasks highly realistic (6.56/7). Programmers took roughly 5–12 minutes per task. Our data is **synthetic** in exactly that shape (invented titles and author names; real institution names).
- **Tags:** JSON · nested lists (papers → authors) · set-based de-duplication · dict inversion · sort by count
- **Data:** `chi15.papers.json` (14 papers) and `chi15.sessions.json` (6 sessions) — shared by all four `chi-*` tasks.
- **Stdlib used in solution:** `json`
- **Difficulty:** easy (task 1) / easy–medium (task 2)
- **Shape:** nested JSON → dict of sets → sorted report

## Task description (as given to participant)

`chi15.papers.json` is a list of conference papers; each paper has `keywords` (a list of strings) and `authors` (a list of objects with `name`, `institution`, `city`, `country`). Write a script that prints:

1. How many papers have `"social"` among their keywords, followed by their IDs and titles.
2. A table of the number of papers per institution, sorted by count descending then name, and then the **top 3 institutions**.

A paper counts **once** for an institution even if several of its authors are from that institution.

## Expected output

```
Papers with keyword 'social': 3
  102  Social Signals in Group Chat
  104  Wearables for Social Anxiety
  110  A Social Robot for Classroom Engagement

Papers per institution:
   5  Carnegie Mellon University
   5  University of Washington
   3  KTH Royal Institute of Technology
   3  University of Michigan
   3  University of Tokyo

Top 3 institutions:
  Carnegie Mellon University (5 papers)
  University of Washington (5 papers)
  KTH Royal Institute of Technology (3 papers)
```

## Notes for study designers

- These are study tasks 1 and 2. Task 2 is the thesis's headline example: the Excel group had to flatten papers×authors into a "long table", which *double counts* a paper with two authors from the same institution. In Python the natural fix is `institution -> set(paper IDs)`; a version using `Counter` over authors is a ready-made buggy starting script (it reports CMU = 6, UW = 6).
- Stages: (1) list filter on a nested list field; (2) invert the nesting (papers → institutions); (3) sort by two keys and slice.
- Extensions: count by country; treat keywords case-insensitively; require "social" only as a whole keyword vs. substring ("social media").

## Example solution

```python
# CHI'15 papers: (a) how many papers have "social" among their keywords;
# (b) the top 3 institutions by number of DISTINCT papers.
import json

with open("chi15.papers.json") as f:
    papers = json.load(f)

# (a) keyword filter
social = [p for p in papers if "social" in p["keywords"]]
print(f"Papers with keyword 'social': {len(social)}")
for p in social:
    print(f"  {p['ID']}  {p['paper_title']}")

# (b) institution -> set of paper IDs (a set, so two CMU authors on one
# paper count that paper once)
papers_by_inst = {}
for p in papers:
    for a in p["authors"]:
        papers_by_inst.setdefault(a["institution"], set()).add(p["ID"])

ranked = sorted(papers_by_inst.items(), key=lambda kv: (-len(kv[1]), kv[0]))
print()
print("Papers per institution:")
for inst, ids in ranked:
    print(f"  {len(ids):>2}  {inst}")
print()
print("Top 3 institutions:")
for inst, ids in ranked[:3]:
    print(f"  {inst} ({len(ids)} papers)")
```
