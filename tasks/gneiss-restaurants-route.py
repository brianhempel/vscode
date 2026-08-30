# Top-5 rated restaurants from a Yelp-style search response, driving time
# from a fixed origin (mock Directions response), and a Static Maps URL with
# one marker per restaurant.
import json

with open("gneiss-restaurants-route.input.json") as f:
    businesses = json.load(f)["businesses"]
with open("gneiss-restaurants-route.directions.json") as f:
    directions = json.load(f)

# Sort by rating desc, then review_count desc; keep the first five.
top5 = sorted(businesses, key=lambda b: (-b["rating"], -b["review_count"]))[:5]

print(f"Origin: {directions['origin']}")
print(f"{'':2}{'Restaurant':<28}{'Rating':>6}{'Reviews':>9}  {'Address':<22}{'Drive':>8}")
markers = ""
for letter, b in zip("ABCDE", top5):
    address = b["location"]["address1"]
    route = directions["routes"].get(address)
    drive = route["duration_text"] if route else "n/a"
    print(f"{letter:<2}{b['name']:<28}{b['rating']:>6}{b['review_count']:>9}  {address:<22}{drive:>8}")
    lat, lng = b["coordinates"]["latitude"], b["coordinates"]["longitude"]
    # Same shape as the spreadsheet formula in the thesis:
    #   CONCATENATE("&markers=label:", F1, "|", D1, ",", E1)
    markers += f"&markers=label:{letter}|{lat},{lng}"

url = "https://maps.googleapis.com/maps/api/staticmap?size=600x400" + markers
print()
print("Static map URL:")
print(url)
