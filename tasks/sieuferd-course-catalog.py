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

if __name__ == "__main__":
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
