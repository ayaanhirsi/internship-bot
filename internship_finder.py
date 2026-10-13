#!/usr/bin/env python3
"""
Internship finder: cybersecurity / DevSecOps / security-engineering internships
for Winter 2027 and Summer 2027, ranked against Ayaan's resume.

Sources (all public, no API keys):
  1. GitHub internship lists (SimplifyJobs-style listings.json)
  2. Greenhouse company boards
  3. Lever company boards
  4. Google Careers (no stable public API, so it prints pre-filtered search links)

Usage:
    pip install requests
    python internship_finder.py                  # Canada + US + remote, top 40
    python internship_finder.py --region canada  # or --region us
    python internship_finder.py --top 100 --min-score 6

Output: internships.csv (full ranked list) + printed top results.
"""
import argparse
import csv
import html
import re
import sys
import urllib.parse
from concurrent.futures import ThreadPoolExecutor

import requests

# --------------------------------------------------------------------------
# CONFIG: edit freely
# --------------------------------------------------------------------------

# GitHub-hosted listing files. Repo names change each cycle; failures are skipped.
LISTING_SOURCES = [
    "https://raw.githubusercontent.com/SimplifyJobs/Summer2027-Internships/dev/.github/scripts/listings.json",
    "https://raw.githubusercontent.com/SimplifyJobs/Summer2026-Internships/dev/.github/scripts/listings.json",
]

# Company board tokens (the slug in boards.greenhouse.io/<slug> or jobs.lever.co/<slug>).
# Wrong/changed slugs just get skipped, so add as many as you like.
GREENHOUSE = [
    "cloudflare", "datadog", "okta", "gitlab", "mongodb", "databricks",
    "stripe", "anthropic", "elastic", "twilio", "coinbase", "tailscale",
    "1password", "snyk", "wiz", "sentinelone", "zscaler", "rapid7",
    "wealthsimple", "pointclickcare", "stackadapt", "ecobee", "faire",
    "instacart", "robinhood", "figma", "reddit", "asana", "brex",
]
LEVER = ["palantir", "wealthsimple", "kobo", "nuvei", "applyboard", "clearco"]

# Companies you want referral links for (printed at the end).
REFERRAL_TARGETS = ["Google", "RBC", "Cloudflare", "Datadog", "Shopify", "Microsoft", "Amazon"]
SCHOOL = "Seneca Polytechnic"

# Resume-derived keywords and weights (title hits count 3x).
RESUME_KEYWORDS = {
    # core fit
    "security": 3, "cybersecurity": 4, "devsecops": 5, "appsec": 4,
    "application security": 4, "penetration": 4, "pentest": 4, "red team": 3,
    "vulnerability": 3, "threat": 3, "detection": 3, "soc": 2, "incident": 2,
    "intrusion": 4, "malware": 2, "cloud security": 4, "security engineer": 4,
    # tech stack from resume
    "python": 3, "sql": 2, "docker": 3, "kubernetes": 2, "ci/cd": 3,
    "jenkins": 2, "ansible": 2, "aws": 2, "azure": 2, "bash": 2, "powershell": 1,
    "rest api": 2, "fastapi": 2, "machine learning": 2, "ml": 1, "automation": 3,
    "infrastructure": 2, "git": 1, "agile": 1, "linux": 2, "networking": 2,
    "software engineer": 4, "software developer": 4, "backend": 4,
    "full stack": 3, "data engineer": 3, "data science": 3,
    "artificial intelligence": 3, "quantitative": 3, "react": 2,
    "javascript": 2, "node.js": 2, "postgresql": 2, "spark": 2,
    "wireshark": 2, "nmap": 2, "burp": 2, "metasploit": 2, "semgrep": 2,
}
NEGATIVE = {  # things that don't fit a 2nd/3rd-year security student
    "phd": -10, "ph.d": -10, "master's": -4, "mba": -10, "senior": -6, "staff": -6,
    "director": -10, "sales": -6, "marketing": -6, "recruit": -6,
    "legal": -6, "hardware": -3, "mechanical": -6, "electrical": -4,
}
INTERN_WORDS = ("intern", "co-op", "coop", "co op", "student", "apprentice", "new grad intern")
SECURITY_WORDS = ("secur", "cyber", "devsecops", "appsec", "infosec", "threat",
                  "vulnerab", "pentest", "penetration", "soc ", "detection", "risk", "grc",
                  "cloud", "devops", "platform", "software", "sre", "reliab", "data", "ml ", "ai ",
                   "backend", "full stack", "quant", "developer", "engineer", "analytics")

SEASON_PATTERNS = {
    "Winter 2027": r"winter\s*2027|jan(uary)?\s*2027|2027\s*winter|\bw27\b|jan\s*[-–]\s*apr\s*2027",
    "Summer 2027": r"summer\s*2027|may\s*2027|2027\s*summer|\bs27\b|may\s*[-–]\s*aug(ust)?\s*2027",
    "Fall 2027": r"fall\s*2027|autumn\s*2027|sep(tember)?\s*2027|2027\s*fall",
}
GTA = ("toronto", "north york", "scarborough", "etobicoke", "markham",
       "mississauga", "brampton", "vaughan", "richmond hill", "oakville",
       "burlington", "pickering", "ajax", "whitby", "oshawa")
ONTARIO = ("waterloo", "kitchener", "cambridge", "ottawa", "kanata",
           "hamilton", "london, on", "guelph", "kingston", "ontario")
CANADA = ("canada", "toronto", "ontario", "waterloo", "ottawa", "montreal",
          "montréal", "vancouver", "mississauga", "markham", "kitchener",
          "calgary", "edmonton", "halifax", "winnipeg", "quebec",
          "québec", "british columbia", "alberta", "nova scotia")
HEADERS = {"User-Agent": "internship-finder/1.0 (personal use)"}


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------
def clean(text: str) -> str:
    text = html.unescape(text or "")
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def get_json(url, timeout=20):
    try:
        r = requests.get(url, headers=HEADERS, timeout=timeout)
        if r.status_code != 200:
            return None
        return r.json()
    except Exception:
        return None


def make_job(company, title, location, url, desc="", source="", terms=""):
    return {"company": company, "title": title, "location": location,
            "url": url, "desc": clean(desc)[:6000], "source": source, "terms": terms}


# --------------------------------------------------------------------------
# Sources
# --------------------------------------------------------------------------
def fetch_listing_files():
    jobs = []
    for url in LISTING_SOURCES:
        data = get_json(url)
        if not isinstance(data, list):
            print(f"  [skip] {url.split('/')[4]} (not available)", file=sys.stderr)
            continue
        for j in data:
            if j.get("active") is False or j.get("is_visible") is False:
                continue
            locs = j.get("locations") or []
            jobs.append(make_job(
                j.get("company_name", ""), j.get("title", ""),
                "; ".join(locs) if isinstance(locs, list) else str(locs),
                j.get("url", ""), source="github-list",
                terms=" ".join(j.get("terms") or []) + " " + str(j.get("season", "")),
            ))
    return jobs


def fetch_greenhouse(token):
    data = get_json(f"https://boards-api.greenhouse.io/v1/boards/{token}/jobs?content=true")
    out = []
    for j in (data or {}).get("jobs", []):
        title = j.get("title", "")
        if not any(w in title.lower() for w in INTERN_WORDS):
            continue
        out.append(make_job(token.title(), title, (j.get("location") or {}).get("name", ""),
                            j.get("absolute_url", ""), j.get("content", ""), "greenhouse"))
    return out


def fetch_lever(token):
    data = get_json(f"https://api.lever.co/v0/postings/{token}?mode=json")
    out = []
    for j in data or []:
        title = j.get("text", "")
        if not any(w in title.lower() for w in INTERN_WORDS):
            continue
        out.append(make_job(token.title(), title, (j.get("categories") or {}).get("location", ""),
                            j.get("hostedUrl", ""), j.get("descriptionPlain", ""), "lever"))
    return out


def collect():
    jobs = fetch_listing_files()
    with ThreadPoolExecutor(max_workers=12) as ex:
        for res in ex.map(fetch_greenhouse, GREENHOUSE):
            jobs += res
        for res in ex.map(fetch_lever, LEVER):
            jobs += res
    return jobs


# --------------------------------------------------------------------------
# Matching
# --------------------------------------------------------------------------
def detect_season(job):
    blob = f"{job['title']} {job['terms']} {job['desc']}".lower()
    found = [s for s, pat in SEASON_PATTERNS.items() if re.search(pat, blob)]
    return ", ".join(found) if found else ""


def score(job):
    title, desc = job["title"].lower(), job["desc"].lower()
    s, hits = 0, []
    for kw, w in RESUME_KEYWORDS.items():
        pat = r"\b" + re.escape(kw) + r"\b"
        in_title = re.search(pat, title)
        in_desc = re.search(pat, desc)
        if in_title:
            s += w * 3
            hits.append(kw)
        elif in_desc:
            s += w
            hits.append(kw)
    for kw, w in NEGATIVE.items():
        if kw in title:
            s += w
    return s, sorted(set(hits))


US_STATES = ("AL AK AZ AR CA CO CT DE FL GA HI ID IL IN IA KS KY LA ME MD MA MI MN MS MO MT NE NV NH NJ NM "
             "NY NC ND OH OK OR PA RI SC SD TN TX UT VT VA WA WV WI WY DC").split()
US_RE = re.compile(r"\b(united states|usa|u\.s\.|us)\b|,\s*(" + "|".join(US_STATES) + r")\b", re.I)
US_CITIES = ("new york", "san francisco", "seattle", "austin", "boston", "chicago", "mountain view",
             "sunnyvale", "los angeles", "san jose", "washington", "atlanta", "denver", "bellevue")


def location_priority(job):
    """Toronto-first ranking; unknown/remote locations stay eligible."""
    loc = (job.get("location") or "").lower()
    if any(place in loc for place in GTA):
        return 100, "Toronto / GTA"
    if any(place in loc for place in ONTARIO):
        return 70, "Ontario"
    if any(place in loc for place in CANADA):
        return 45, "Canada"
    if US_RE.search(loc) or any(place in loc for place in US_CITIES):
        return 25, "United States"
    return 10, "Remote / Unspecified" if "remote" in loc or not loc else "Other"


def location_ok(job, region):
    """Allow both Canada and US; unknown remote stays eligible."""
    loc = (job.get("location") or "").lower()
    if not loc or "remote" in loc:
        return True
    is_ca = any(c in loc for c in CANADA) or any(c in loc for c in GTA)
    is_us = bool(US_RE.search(loc)) or any(c in loc for c in US_CITIES)
    if region == "canada":
        return is_ca
    if region == "us":
        return is_us
    return is_ca or is_us


def filter_and_rank(jobs, region, min_score):
    seen, ranked = set(), []
    for j in jobs:
        key = (j["company"].lower(), j["title"].lower(), j["url"])
        if key in seen or not j["url"]:
            continue
        seen.add(key)
        text = f"{j['title']} {j['desc'][:500]}".lower()
        if not any(w in j["title"].lower() for w in INTERN_WORDS):
            continue
        if not any(w in text for w in SECURITY_WORDS):
            continue
        if not location_ok(j, region):
            continue
        season = detect_season(j)
        # If a listing names a season and it's neither of ours, drop it (e.g. Fall 2026).
        explicit_other = re.search(r"\b(?:fall|summer|winter|spring)\s*202[0-689]\b|\b202[0-689]\s*(?:fall|summer|winter|spring)\b", f"{j['title']} {j['terms']}".lower())
        if explicit_other and not season:
            continue
        sc, hits = score(j)
        if sc < min_score:
            continue
        bonus, region_label = location_priority(j)
        j.update(season=season or "unspecified", score=sc,
                 priority_score=sc + bonus, region=region_label,
                 matched=", ".join(hits))
        ranked.append(j)
    ranked.sort(key=lambda x: (x["priority_score"], x["season"] != "unspecified"), reverse=True)
    return ranked


# --------------------------------------------------------------------------
# Google + referral helpers
# --------------------------------------------------------------------------
def google_links(region="both"):
    base = "https://www.google.com/about/careers/applications/jobs/results/"
    places = {"canada": ["Canada"], "us": ["United States"], "both": ["Canada", "United States"]}[region]
    queries = ["security intern", "software engineering intern", "STEP intern", "cloud security intern"]
    links = []
    for place in places:
        for q in queries:
            qs = urllib.parse.urlencode({"q": q, "location": place, "target_level": "INTERN_AND_APPRENTICE"})
            links.append((f"{q} ({place})", f"{base}?{qs}"))
    return links


def referral_links(company):
    kw = urllib.parse.quote(f"{company} {SCHOOL}")
    alumni = f"https://www.linkedin.com/search/results/people/?keywords={kw}"
    cs = urllib.parse.quote(f"{company} ColorStack")
    colorstack = f"https://www.linkedin.com/search/results/people/?keywords={cs}"
    return alumni, colorstack


# --------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--region", choices=["both", "canada", "us"], default="both",
                    help="where to look (default: both Canada and US)")
    ap.add_argument("--top", type=int, default=40)
    ap.add_argument("--min-score", type=int, default=8)
    ap.add_argument("--out", default="internships.csv")
    args = ap.parse_args()

    print("Fetching listings...", file=sys.stderr)
    jobs = collect()
    print(f"  pulled {len(jobs)} raw postings", file=sys.stderr)
    ranked = filter_and_rank(jobs, args.region, args.min_score)

    with open(args.out, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["priority_score", "score", "region", "season", "company", "title", "location", "matched_keywords", "url", "source"])
        for j in ranked:
            w.writerow([j["priority_score"], j["score"], j["region"], j["season"], j["company"], j["title"], j["location"],
                        j["matched"], j["url"], j["source"]])

    print(f"\n=== Region: {args.region} | Top {min(args.top, len(ranked))} of {len(ranked)} matches (saved to {args.out}) ===\n")
    for j in ranked[: args.top]:
        print(f"[{j['priority_score']:>3}] {j['company']} | {j['title']} | {j['location'] or 'n/a'} | {j['season']}")
        print(f"      matched: {j['matched']}")
        print(f"      {j['url']}\n")

    print("=== Google Careers (open these, filtered to interns) ===")
    for q, link in google_links(args.region):
        print(f"  {q}: {link}")

    print("\n=== Referral searches (LinkedIn) ===")
    for c in REFERRAL_TARGETS:
        alumni, cs = referral_links(c)
        print(f"  {c}\n    {SCHOOL} people: {alumni}\n    ColorStack people: {cs}")


if __name__ == "__main__":
    main()
