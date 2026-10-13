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

ranked = f.filter_and_rank(f.collect(), "both", 8)
new = [j for j in ranked if j["url"] not in seen][:15]
sent = []
for j in new:
    msg = (f"**{j['company']}** | {j['title']}\n"
           f"📍 {j['location'] or 'Not specified'} ({j['region']})\n"
           f"📅 {j['season']} | Match {j['score']} | Priority {j['priority_score']}\n"
           f"{j['url']}")
    try:
        r = requests.post(hook, json={"content": msg}, timeout=15)
        if r.status_code in (200, 204):
            sent.append(j["url"])
        else:
            print(f"Discord returned {r.status_code}: {r.text[:200]}")
    except requests.RequestException as exc:
        print(f"Discord delivery failed: {exc}")
    time.sleep(1)

SEEN.write_text(json.dumps(sorted(seen | set(sent)), indent=2))
print(f"matched {len(ranked)}, sent {len(sent)} new roles")
