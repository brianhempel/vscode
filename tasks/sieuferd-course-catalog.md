# SIEUFERD course catalog: nested report and hierarchy inversion

- **Source:** Eirik Bakke & David R. Karger, "Expressive Query Construction through Direct Manipulation of Nested Relational Results", SIGMOD 2016 — https://doi.org/10.1145/2882903.2915210 ; also Bakke's MIT PhD thesis (2016), §3.3.1 "Standardized tasks" 3–6 (auto joins and filters). In the study, users started from a single base table and had to build a report-style query like the course catalog in the paper's Figure 1 (courses with readings and sections), first via a single join (readings), then via a multi-hop join (sections → instructors_sections → instructors), then filter to "Spring 06-07" (semester names live in a separate table), and finally rebuild the query from the *instructors* end to list courses per instructor. The data here is the synthetic 8-course mini database shared with `related-worksheets-courses` (invented instructor names — substituted for the paper's real ones so no fabricated records are attached to real people).
- **Tags:** CSV tables → nested structure · group-by into dict-of-lists · multi-hop join through a link table · filter that reaches through a join (semester) · inverting a hierarchy · indented outline rendering · JSON out
- **Data:** shared `course-db.*.csv` (courses 8, instructors 8, sections 13, section_instructors 13, readings 11, semesters 2).
- **Stdlib used in solution:** `csv`, `json`
- **Difficulty:** medium (~20 minutes)
- **Shape:** flat tables → nested dict/list report → text outline, and the reverse grouping (instructor → courses)

## Task description (as given to participant)

The files `course-db.*.csv` form a small course database (see `related-worksheets-courses.md` for the column list; sections also have a `semester_id` that refers to `course-db.semesters.csv`, which has `id,name`).

Write a script that:

1. Builds a nested **course catalog**: for every course, its list of reading titles, and its list of sections; each section carries its section code, type, semester name, and the *names* of its instructors (found through `section_instructors.csv`).
2. Keeps only sections offered in **Spring 06-07**, and drops courses that then have no sections left.
3. Prints the catalog as an indented outline: a line `CODE: Title`, then one indented `reading: …` line per reading, then one indented line per section showing section code, type, semester and instructor names.
4. Inverts the hierarchy and prints, for every instructor (alphabetically), the courses they teach in that semester with the section codes in parentheses, e.g. `Theo Lindqvist: HIS 383 (L01, P01)`.
5. Prints the second course of the filtered catalog as a single-line JSON object.

## Expected output

```
== Courses offered in Spring 06-07 ==
MUS 105: Music Theory Through Performance and Composition
    reading: Harmony and Voice Leading
    reading: The Study of Counterpoint
    L01 lecture Spring 06-07 Miriam Oduya
    P01 precept Spring 06-07 Miriam Oduya
KOR 107: Intermediate Korean II
    reading: Integrated Korean: Intermediate 2
    L01 lecture Spring 06-07 Hana Kobayashi
HIS 383: The United States Since 1920
    reading: Grand Expectations
    reading: The Age of Reform
    L01 lecture Spring 06-07 Theo Lindqvist
    P01 precept Spring 06-07 Theo Lindqvist
    P02 precept Spring 06-07 Desmond Okafor
COS 226: Algorithms and Data Structures
    reading: Algorithms (4th ed.)
    L01 lecture Spring 06-07 Samuel Achterberg
    P01 precept Spring 06-07 Ingrid Halvorsen
ART 220: Modern Architecture
    reading: Modern Architecture Since 1900
    reading: Towards a New Architecture
    L01 lecture Spring 06-07 Priya Venkataraman

== Courses per instructor (Spring 06-07) ==
Desmond Okafor: HIS 383 (P02)
Hana Kobayashi: KOR 107 (L01)
Ingrid Halvorsen: COS 226 (P01)
Miriam Oduya: MUS 105 (L01, P01)
Priya Venkataraman: ART 220 (L01)
Samuel Achterberg: COS 226 (L01)
Theo Lindqvist: HIS 383 (L01, P01)

== One course as nested JSON ==
{"code": "KOR 107", "title": "Intermediate Korean II", "readings": ["Integrated Korean: Intermediate 2"], "sections": [{"section": "L01", "type": "lecture", "semester": "Spring 06-07", "instructors": ["Hana Kobayashi"]}]}
```

## Notes for study designers

- This is the same data as `related-worksheets-courses` but the opposite kind of task: not "find one fact" but "build the whole nested structure and render it". In SIEUFERD terms: auto-join readings (one hop), auto-join sections→instructors (three hops), filter on a field from a not-yet-joined table (semester), then start over from the other end of the schema.
- Natural stages map 1:1 to the study's tasks 3, 4, 5, 6, so a study can stop after any of them.
- Good edit-the-script moments: start with a version that filters by `semester_id == "2"` hard-coded and ask participants to make it take the semester *name*; ask them to add a `readings` count column; ask for the inverted view to also include readings; ask for courses with *no* readings to print `(no readings)`.
- The `group()` helper (rows → dict of lists) is the reusable idiom; expect participants to write it three times before extracting it — a good refactoring prompt.
- The JSON line is deliberately compact so the expected output stays short; switching it to `indent=2` is a trivial stage.

## Example solution

```python
# SIEUFERD-style nested report: build a course catalog (course -> readings,
# sections -> instructors) from flat CSV tables, filter it to one semester,
# then invert the hierarchy (instructor -> courses).
import csv, json

def load(name):
    with open(f"course-db.{name}.csv", newline="") as f:
        return list(csv.DictReader(f))

courses = load("courses")
instructors = {i["id"]: i for i in load("instructors")}
semesters = {s["id"]: s["name"] for s in load("semesters")}
sections = load("sections")
links = load("section_instructors")
readings = load("readings")

def group(rows, key):
    """rows -> {key value: [rows with that key]}"""
    out = {}
    for r in rows:
        out.setdefault(r[key], []).append(r)
    return out

readings_by_course = group(readings, "course_code")
sections_by_course = group(sections, "course_code")
links_by_section = group(links, "section_id")

def build_catalog(semester_name=None):
    """Nested list: one entry per course, with readings and sections (each with
    its instructors). If semester_name is given, keep only sections in that
    semester and drop courses with no remaining sections (auto-join + filter)."""
    catalog = []
    for c in courses:
        secs = []
        for s in sections_by_course.get(c["code"], []):
            if semester_name and semesters[s["semester_id"]] != semester_name:
                continue
            secs.append({
                "section": s["section_code"],
                "type": s["type"],
                "semester": semesters[s["semester_id"]],
                "instructors": [instructors[l["instructor_id"]]["name"]
                                for l in links_by_section.get(s["id"], [])],
            })
        if semester_name and not secs:
            continue
        catalog.append({
            "code": c["code"],
            "title": c["title"],
            "readings": [r["title"] for r in readings_by_course.get(c["code"], [])],
            "sections": secs,
        })
    return catalog

def invert(catalog):
    """instructor -> sorted list of 'CODE (L01, P01)' strings."""
    by_instructor = {}
    for course in catalog:
        for sec in course["sections"]:
            for name in sec["instructors"]:
                by_instructor.setdefault(name, {}).setdefault(course["code"], []).append(sec["section"])
    return {name: [f"{code} ({', '.join(secs)})" for code, secs in sorted(cs.items())]
            for name, cs in sorted(by_instructor.items())}

def outline(catalog):
    lines = []
    for course in catalog:
        lines.append(f"{course['code']}: {course['title']}")
        for r in course["readings"]:
            lines.append(f"    reading: {r}")
        for sec in course["sections"]:
            who = ", ".join(sec["instructors"]) or "(no instructor)"
            lines.append(f"    {sec['section']} {sec['type']:<7} {sec['semester']:<12} {who}")
    return "\n".join(lines)

spring = build_catalog("Spring 06-07")
print("== Courses offered in Spring 06-07 ==")
print(outline(spring))
print()
print("== Courses per instructor (Spring 06-07) ==")
for name, cs in invert(spring).items():
    print(f"{name}: {'; '.join(cs)}")
print()
print("== One course as nested JSON ==")
print(json.dumps(spring[1]))
```
