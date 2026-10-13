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
    sys.exit("DISCORD_WEBHOOK is not set. Run: set DISCORD_WEBHOOK=your-url")

ranked = f.filter_and_rank(f.collect(), "both", 8)
new = [j for j in ranked if j["url"] not in seen][:15]  # cap per run

sent = []
for j in new:
    msg = (f"**{j['company']}** | {j['title']} | {j['location'] or 'n/a'} | "
           f"{j['season']} (score {j['score']})\n{j['url']}")
    r = requests.post(hook, json={"content": msg}, timeout=15)
    if r.status_code in (200, 204):
        sent.append(j["url"])
    else:
        print(f"Discord returned {r.status_code}: {r.text[:200]}")
    time.sleep(1)  # stay under Discord's rate limit

# only mark what was actually delivered, so the rest trickle in on later runs
SEEN.write_text(json.dumps(sorted(seen | set(sent))))
print(f"matched {len(ranked)}, sent {len(sent)} new roles")
