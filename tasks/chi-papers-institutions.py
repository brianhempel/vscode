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
