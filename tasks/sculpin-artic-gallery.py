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

if __name__ == "__main__":
    fields = ["id", "title", "artist_title", "date_display", "image_id", "department_title"]
    print("Query URL:", build_query_url("cats", fields))
    print()
    with open("sculpin-artic-gallery.input.json") as f:
        response = json.load(f)
    groups = group_by_artist(response["data"], response["config"]["iiif_url"])
    print(render_markdown("cats", groups, response["pagination"]["total"]))
