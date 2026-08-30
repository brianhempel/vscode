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
