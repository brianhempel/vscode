# ARTIC artwork gallery from a JSON API response

- **Source:** Josh Horowitz & Jeffrey Heer, "Sculpin: Direct-Manipulation Transformation of JSON" (2025), Figure 5 — an interactive gallery of Art Institute of Chicago artworks matching a query, built inside Sculpin from the AIC public API (itself a recreation of an example from Horowitz & Heer's earlier work). API docs: https://api.artic.edu/docs/ (no key needed). The data file is a **real** response captured from `https://api.artic.edu/api/v1/artworks/search?q=cats&limit=8&fields=id,title,artist_title,date_display,image_id,department_title` (metadata is published by the museum under CC0).
- **Tags:** URL string composition · nested JSON (`data[]`, `config.iiif_url`, `pagination.total`) · null handling · group-by into dict of lists · Markdown rendering
- **Data:** `sculpin-artic-gallery.input.json` — 8 artworks; one has `artist_title: null`, one has `image_id: null`.
- **Stdlib used in solution:** `json`
- **Difficulty:** easy–medium
- **Shape:** string (query) → URL string; nested JSON → grouped dict → strings (image URLs) → Markdown text

## Task description (as given to participant)

The Art Institute of Chicago has a public search API. `sculpin-artic-gallery.input.json` is the response it returned for the query "cats". It has the shape

```
{"data": [{"id": 656, "title": "...", "artist_title": "Edward Kemeys" or null,
           "date_display": "1893", "image_id": "6b1e..." or null, "department_title": "..."}, ...],
 "pagination": {"total": 132681, ...},
 "config": {"iiif_url": "https://www.artic.edu/iiif/2", ...}}
```

Write a script that:

1. Builds and prints the query URL for a search term and a list of fields: `https://api.artic.edu/api/v1/artworks/search?q=<term>&limit=8&fields=<f1,f2,...>` (spaces in the term become `%20`).
2. Loads the response and, for each artwork, computes its image URL `<config.iiif_url>/<image_id>/full/843,/0/default.jpg` (artworks without an `image_id` have no image).
3. Groups the artworks by artist (`artist_title`; `null` → `Unknown artist`).
4. Prints a Markdown gallery: a title line `# Artworks matching "cats" (<total> in collection, showing <n>)`, then for each artist in alphabetical order a `## <artist>` heading followed by one bullet per artwork, `- [<title> (<date>)](<image url>)`, or `- <title> (<date>) *(no image)*` when there is no image. Put a blank line after each group.

## Expected output

```
Query URL: https://api.artic.edu/api/v1/artworks/search?q=cats&limit=8&fields=id,title,artist_title,date_display,image_id,department_title

# Artworks matching "cats" (132681 in collection, showing 8)

## Edward Kemeys
- [Lion (One of a Pair, South Pedestal) (1893)](https://www.artic.edu/iiif/2/6b1edb9c-0f3f-0ee3-47c7-ca25c39ee360/full/843,/0/default.jpg)

## Inagaki Tomoo
- [Cat Making Up (1962)](https://www.artic.edu/iiif/2/9dbfc5f2-4a2a-3373-d483-4314a3cdc195/full/843,/0/default.jpg)

## Nasca
- Border Fragments (100 BCE–200 CE) *(no image)*

## Pablo Picasso
- [Nude with Cats (1901)](https://www.artic.edu/iiif/2/96c25381-bdfb-81c4-de91-1186aa38ace4/full/843,/0/default.jpg)

## René Magritte
- [Homesickness (c. 1948)](https://www.artic.edu/iiif/2/0366abf0-fb3c-4631-71f5-e2574b31de9e/full/843,/0/default.jpg)

## Romare Howard Bearden
- [The Return of Odysseus (Homage to Pinturicchio and Benin) (1977)](https://www.artic.edu/iiif/2/42d31893-d3ff-3fbd-bd05-2e02b2162e07/full/843,/0/default.jpg)

## Théophile-Alexandre Pierre Steinlen
- [Winter: Cat on a Cushion (1909)](https://www.artic.edu/iiif/2/e8e67721-bbb1-d007-82bd-c430ea73db70/full/843,/0/default.jpg)

## Unknown artist
- [Baroque Pearl Mounted as a Cat Holding a Mouse (17th century)](https://www.artic.edu/iiif/2/fe394433-14ae-89e0-136f-31cbdb390771/full/843,/0/default.jpg)
```

## Notes for study designers

- Stages: (1) string composition (URL); (2) nested field access with two different `null`s to handle; (3) group-by; (4) render. Each stage is small and visible.
- Live variant: replace the `open()` with `urllib.request.urlopen(build_query_url(...)).read()` — the API is keyless and CORS-friendly, so the task can be run against the real service and the query term changed by participants. Keep `limit` small.
- Edit-the-script moments: change the query term and field list; add a `department_title` sub-grouping; change the image width from 843 to a thumbnail size (the IIIF URL segment); sort artists by number of works instead of name.
- The two `null`s are the natural bugs: a first version that does `art["artist_title"]` as a dict key will produce a `None` heading, and building the image URL for `image_id: null` yields a broken link.

## Example solution

```python
# Art Institute of Chicago gallery: build the search URL, derive IIIF image
# URLs from the API response, group artworks by artist and render Markdown.
import json

API_BASE = "https://api.artic.edu/api/v1/artworks/search"

def build_query_url(term, fields, limit=8):
    """Compose the search URL: ?q=<term>&limit=<n>&fields=<a,b,c>."""
    term = term.replace(" ", "%20")
    return f"{API_BASE}?q={term}&limit={limit}&fields={','.join(fields)}"

def image_url(iiif_base, image_id, width=843):
    if not image_id:
        return None
    return f"{iiif_base}/{image_id}/full/{width},/0/default.jpg"

def group_by_artist(artworks, iiif_base):
    groups = {}
    for art in artworks:
        artist = art.get("artist_title") or "Unknown artist"
        entry = {
            "id": art["id"],
            "title": art["title"],
            "date": art.get("date_display") or "n.d.",
            "image": image_url(iiif_base, art.get("image_id")),
        }
        groups.setdefault(artist, []).append(entry)
    return groups

def render_markdown(term, groups, total):
    lines = [f"# Artworks matching \"{term}\" ({total} in collection, showing {sum(len(v) for v in groups.values())})", ""]
    for artist in sorted(groups):
        lines.append(f"## {artist}")
        for e in groups[artist]:
            label = f"{e['title']} ({e['date']})"
            lines.append(f"- [{label}]({e['image']})" if e["image"] else f"- {label} *(no image)*")
        lines.append("")
    return "\n".join(lines).rstrip()

fields = ["id", "title", "artist_title", "date_display", "image_id", "department_title"]
print("Query URL:", build_query_url("cats", fields))
print()
with open("sculpin-artic-gallery.input.json") as f:
    response = json.load(f)
groups = group_by_artist(response["data"], response["config"]["iiif_url"])
print(render_markdown("cats", groups, response["pagination"]["total"]))
```
