# Related Worksheets: course-database lookups

- **Source:** Eirik Bakke, David R. Karger, Robert C. Miller, "A spreadsheet-based user interface for managing plural relationships in structured data", CHI 2011 — https://doi.org/10.1145/1978942.1979313 . The paper's Mechanical Turk study (36 workers) compared Excel with *Related Worksheets* on a normalized course database (a subset of a real course catalog: 37 courses with Instructors, Sections, Meetings, GradingComponents, Readings…) using the five lookup tasks in its Table 1. The five questions below are those tasks; the database here is a synthetic 8-course mini version in the same normalized shape, and the instructor names are invented (the paper's real instructor names were substituted, so that no fabricated e-mail addresses, schedules or grading schemes are attached to real people).
- **Tags:** multiple CSV tables · building dict indexes · multi-hop joins (course → section → section_instructors → instructor) · filtering · parsing `HH:MM` times · string prefix extraction (`"KOR 107: …"` → code)
- **Data:** shared `course-db.*.csv` — `courses` (8), `instructors` (8), `sections` (13), `section_instructors` (13), `meetings` (18), `grading` (22), `readings` (11), `semesters` (2). Also used by `sieuferd-course-catalog`.
- **Stdlib used in solution:** `csv`
- **Difficulty:** medium (each question is small; the join plumbing is the work)
- **Shape:** flat CSV tables → dict indexes / nested lookups → short answer strings

## Task description (as given to participant)

The files `course-db.*.csv` are a small course-management database, one table per file:

- `courses.csv` — `code,title,distribution_area`
- `instructors.csv` — `id,name,email`
- `sections.csv` — `id,course_code,section_code,type,semester_id` (type is `lecture` or `precept`; section codes look like `L01`, `P01`)
- `section_instructors.csv` — `section_id,instructor_id` (who teaches which section)
- `meetings.csv` — `section_id,day,start_time,end_time` (times as `HH:MM`, 24-hour)
- `grading.csv` — `course_code,component,percent`
- `readings.csv` — `course_code,title`

Write a script that prints the answers to these five questions, one per line, numbered:

1. Which course(s) does **Theo Lindqvist** teach? (Print as `CODE: Title`.)
2. In "MUS 105: Music Theory Through Performance and Composition", what percentage of the final grade comes from the **Midterm Exam**?
3. Which course(s) in the **LA** distribution area have a lecture section `L01` with a meeting that starts **after 12:00**?
4. What is the e-mail address of the instructor who teaches "KOR 107: Intermediate Korean II"?
5. Who teaches the **precept** section of "HIS 383: The United States Since 1920" that meets on **Wednesdays at 10:00**?

Where a question names a course as `"CODE: Title"`, take the code from that string rather than hard-coding it separately.

## Expected output

```
1. HIS 383: The United States Since 1920
2. 25%
3. ENG 212: Shakespeare and the Early Modern Stage, ART 220: Modern Architecture
4. hkobayashi@example.edu
5. Theo Lindqvist
```

## Notes for study designers

- These are pure *lookup* questions, so the interesting part for a script-editing tool is the scaffolding: loading several CSVs, building `id → row` and `key → [rows]` dictionaries, and chaining lookups through the link table `section_instructors`. Each question is then a 5–10-line function.
- Small string steps: `"KOR 107: Intermediate Korean II".split(":")[0]` to get the code; `"13:30" → minutes` to compare with noon; `"Wed"` day matching.
- Good edit-the-script moments: (a) start participants with a version that only looks at *lecture* sections and ask why question 5 (a precept) returns nothing; (b) ask for question 3 to be changed to "starts after 12:00 **on Tuesdays**"; (c) ask them to also print, for question 1, the section codes taught.
- In the original study the Excel condition took noticeably longer on the multi-join task (task 4 in their numbering); this maps to the same multi-hop path here.
- The same dataset backs `sieuferd-course-catalog` (report generation and hierarchy inversion), so the two can be run back-to-back with no new data to learn.

## Example solution

```python
# Related Worksheets study tasks: answer five lookup questions over a small
# normalized course database stored as CSV files (one table per file).
import csv

def load(name):
    with open(f"course-db.{name}.csv", newline="") as f:
        return list(csv.DictReader(f))

courses = load("courses")
instructors = load("instructors")
sections = load("sections")
section_instructors = load("section_instructors")
meetings = load("meetings")
grading = load("grading")

# --- indexes (dict lookups instead of nested loops) ---
course_by_code = {c["code"]: c for c in courses}
instructor_by_id = {i["id"]: i for i in instructors}
section_by_id = {s["id"]: s for s in sections}

instructors_of_section = {}          # section_id -> [instructor dict]
for link in section_instructors:
    instructors_of_section.setdefault(link["section_id"], []).append(
        instructor_by_id[link["instructor_id"]])

meetings_of_section = {}             # section_id -> [meeting dict]
for m in meetings:
    meetings_of_section.setdefault(m["section_id"], []).append(m)

sections_of_course = {}              # course_code -> [section dict]
for s in sections:
    sections_of_course.setdefault(s["course_code"], []).append(s)

def full_title(code):
    return f"{code}: {course_by_code[code]['title']}"

def minutes(hhmm):
    h, m = hhmm.split(":")
    return int(h) * 60 + int(m)

def code_of_title(text):
    """'KOR 107: Intermediate Korean II' -> 'KOR 107'"""
    return text.split(":")[0].strip()

# 1. A course taught by a given instructor (any section they teach).
def courses_taught_by(name):
    found = []
    for s in sections:
        if any(i["name"] == name for i in instructors_of_section.get(s["id"], [])):
            if s["course_code"] not in found:
                found.append(s["course_code"])
    return found

# 2. Percentage of the final grade from one grading component.
def grade_percent(course_code, component):
    for g in grading:
        if g["course_code"] == course_code and g["component"] == component:
            return g["percent"]
    return None

# 3. Courses in a distribution area whose L01 lecture starts after noon.
def afternoon_lectures(area, section_code="L01"):
    result = []
    for c in courses:
        if c["distribution_area"] != area:
            continue
        for s in sections_of_course.get(c["code"], []):
            if s["section_code"] == section_code and any(
                    minutes(m["start_time"]) > 12 * 60
                    for m in meetings_of_section.get(s["id"], [])):
                result.append(c["code"])
    return result

# 4. E-mail of the instructor of a course (lecture section).
def instructor_emails(course_code):
    emails = []
    for s in sections_of_course.get(course_code, []):
        if s["type"] == "lecture":
            emails += [i["email"] for i in instructors_of_section.get(s["id"], [])]
    return emails

# 5. Who teaches the precept of a course meeting on a given day and time.
def precept_teacher(course_code, day, start_time):
    for s in sections_of_course.get(course_code, []):
        if s["type"] != "precept":
            continue
        for m in meetings_of_section.get(s["id"], []):
            if m["day"] == day and m["start_time"] == start_time:
                return [i["name"] for i in instructors_of_section.get(s["id"], [])]
    return []

if __name__ == "__main__":
    print("1.", ", ".join(full_title(c) for c in courses_taught_by("Theo Lindqvist")))
    mus = code_of_title("MUS 105: Music Theory Through Performance and Composition")
    print("2.", grade_percent(mus, "Midterm Exam") + "%")
    print("3.", ", ".join(full_title(c) for c in afternoon_lectures("LA")))
    kor = code_of_title("KOR 107: Intermediate Korean II")
    print("4.", ", ".join(instructor_emails(kor)))
    his = code_of_title("HIS 383: The United States Since 1920")
    print("5.", ", ".join(precept_teacher(his, "Wed", "10:00")))
```
