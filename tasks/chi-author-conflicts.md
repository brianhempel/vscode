# CHI'15 author scheduling conflicts

- **Source:** Kerry Shih-Ping Chang, *Using Web Services and Creating Interactive Web Applications in Spreadsheet Programs* (Gneiss), PhD thesis, CMU HCII, ch. 5 §5.5.4 user study; published as Chang & Myers, "Using and Exploring Hierarchical Data in Spreadsheets", CHI 2016 — https://doi.org/10.1145/2858036.2858506 . In that between-subjects study 12 spreadsheet users (Gneiss vs. Excel) and 6 programmers (JavaScript/Python in Sublime) did five tasks on two JSON files from CHI'15: `papers.json` (484 papers: `ID`, `paper_title`, `abstract`, `keywords[]`, `type` long/short, `award` none/bp/hm, `authors[{name, institution, city, country}]`) and `sessions.json` (119 sessions: `session_title`, `room`, `day`, `time`, `chair`, `submissions[]` of paper IDs). Participants rated the tasks highly realistic (6.56/7). Programmers took roughly 5–12 minutes per task. Our data is **synthetic** in exactly that shape (invented titles and author names; real institution names).
- **Tags:** JSON · three-level nesting (session → paper → author) · inverted index · grouping the same list two ways · sorting
- **Data:** `chi15.papers.json` (14 papers) and `chi15.sessions.json` (6 sessions) — shared by all four `chi-*` tasks.
- **Stdlib used in solution:** `json`
- **Difficulty:** medium–hard (~15–20 min)
- **Shape:** nested JSON → inverted index (author → appearances) → two groupings → text

## Task description (as given to participant)

The conference wants to know whether anyone has a scheduling problem. Using `chi15.sessions.json` and `chi15.papers.json`:

- **Stage 1:** print every author who has two or more papers in the **same session**, with the session, its day/time and the paper titles.
- **Stage 2:** print every author who has papers in **different sessions that run in the same time slot** (same day and time) — a real conflict, since they can't present in two rooms at once.

Sort authors alphabetically.

## Expected output

```
Stage 1: two or more papers in the same session
  Dilnoza Karimova -- Crowdsourcing I (Monday 11:00-12:20): Crowdsourcing Map Corrections in Rural Areas / Paying the Crowd Fairly: Wage Estimation on Microtask Platforms
  Grace Okonkwo -- Accessibility & Aging (Tuesday 14:00-15:20): Designing Voice Assistants for Older Adults / Notifications That Respect Focus Time
  Mei-Lin Huang -- Wearables & Health (Tuesday 09:00-10:20): Wearables for Social Anxiety / Gesture Elicitation for Smart Glasses
  Priya Raman -- Social Computing (Monday 11:00-12:20): Social Signals in Group Chat / Privacy Attitudes in Social Media Sharing
  Tomasz Wielgus -- Crowdsourcing I (Monday 11:00-12:20): Crowd-Powered Captioning for Live Lectures / Paying the Crowd Fairly: Wage Estimation on Microtask Platforms

Stage 2: papers in different sessions in the same time slot
  Olu Adeyemi -- Tuesday 09:00-10:20: End-User Programming vs Wearables & Health
  Priya Raman -- Monday 11:00-12:20: Crowdsourcing I vs Social Computing
```

## Notes for study designers

- Study task 5 — the hardest in the original study (5 of 6 Excel users and 2 of 6 programmers failed within 15 min). The natural structure is an `author -> list of appearances` index built by walking sessions → papers → authors, then two different groupings of that list. Stage 2 is our addition; it reuses the index with a different key, which is a nice "edit the script" step.
- Gotcha: the same author string must match exactly; a variant with `"P. Raman"` vs `"Priya Raman"` turns this into a name-normalisation task.
- Extension: output as JSON instead of text; count total "person-slots".

## Example solution

```python
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
```
