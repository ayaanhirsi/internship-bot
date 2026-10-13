
import json
import os
import pathlib
import sys
import time

import requests
import internship_finder as f

SEEN = pathlib.Path("seen.json")
seen = set(json.loads(SEEN.read_text())) if SEEN.exists() else set()

hook = os.environ.get("DISCORD_WEBHOOK")
if not hook:
    sys.exit("DISCORD_WEBHOOK is not set")

# Toronto first, then Ontario, Canada, and US
GTA = [
    "toronto", "north york", "scarborough",
    "etobicoke", "markham", "mississauga",
    "brampton", "vaughan", "richmond hill",
    "oakville", "burlington", "pickering",
    "ajax", "whitby", "oshawa"
]

ONTARIO = [
    "waterloo", "kitchener", "cambridge",
    "ottawa", "kanata", "hamilton",
    "london", "guelph", "kingston"
]

CANADA = [
    "canada", "ontario", "british columbia",
    "quebec", "alberta", "vancouver",
    "montreal", "calgary", "edmonton",
    "halifax", "winnipeg"
]

USA = [
    "united states", "usa", "u.s.",
    "new york", "seattle", "san francisco",
    "boston", "chicago", "austin",
    "california", "washington", "texas"
]

def location_priority(job):
    location = (job.get("location") or "").lower()

    if any(city in location for city in GTA):
        return 100, "Toronto / GTA"

    if any(city in location for city in ONTARIO):
        return 70, "Ontario"

    if any(place in location for place in CANADA):
        return 45, "Canada"

    if any(place in location for place in USA):
        return 25, "United States"

    return 0, "Other / Unspecified"


# Collect and rank using existing finder
ranked = f.filter_and_rank(f.collect(), "both", 8)

# Add location priority to existing score
for job in ranked:
    bonus, region = location_priority(job)
    job["region"] = region
    job["priority_score"] = job.get("score", 0) + bonus

# Highest priority first
ranked.sort(
    key=lambda j: j["priority_score"],
    reverse=True
)

# Only jobs that haven't been sent
new = [
    j for j in ranked
    if j.get("url") and j["url"] not in seen
][:15]

sent = []

for job in new:
    msg = (
        f"**{job['company']}** | {job['title']}\n"
        f"📍 {job.get('location') or 'Not specified'}\n"
        f"🌎 {job['region']}\n"
        f"📅 {job.get('season', 'Not specified')}\n"
        f"⭐ Match Score: {job['priority_score']}\n"
        f"🔗 {job['url']}"
    )

    response = requests.post(
        hook,
        json={"content": msg},
        timeout=15
    )

    if response.status_code in (200, 204):
        sent.append(job["url"])
    else:
        print(
            f"Discord returned {response.status_code}: "
            f"{response.text[:200]}"
        )

    time.sleep(1)

# Save only successfully delivered jobs
SEEN.write_text(
    json.dumps(sorted(seen | set(sent)), indent=2)
)

print(
    f"Matched {len(ranked)} internships, "
    f"sent {len(sent)} new opportunities"
)
