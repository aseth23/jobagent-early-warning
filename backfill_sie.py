#!/usr/bin/env python3
"""One-off: retro-tag already-seen postings that mention the SIE exam.

The SIE detector was added after ~500 roles had already been posted, so
seen_jobs.json (and therefore the Slack record) under-reports which roles
actually name the exam. This re-fetches descriptions for everything already
seen and adds the marker where it belongs.

Boards are fetched once per token where the platform returns descriptions in
bulk (Greenhouse with content=true, Lever); Workday needs one call per job.

DRY_RUN=1 to report without writing.
"""
from __future__ import annotations

import json
import os
import re
import sys
import urllib.parse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import discover_and_alert as d  # noqa: E402

DRY = os.environ.get("DRY_RUN") == "1"
SIE_RE = re.compile(r"\bSIE\b")


def lever_descriptions(token):
    code, body, _ = d.fetch(f"https://api.lever.co/v0/postings/{token}?mode=json")
    if code != 200:
        return {}
    out = {}
    for p in json.loads(body):
        url = p.get("hostedUrl", "")
        out[url] = (p.get("descriptionPlain", "") or p.get("description", ""))
    return out


def greenhouse_descriptions(token):
    code, body, _ = d.fetch(
        f"https://boards-api.greenhouse.io/v1/boards/{token}/jobs?content=true")
    if code != 200:
        return {}
    out = {}
    for j in json.loads(body).get("jobs", []):
        out[j.get("absolute_url", "")] = j.get("content", "") or ""
    return out


def workday_description(url):
    """Public job URL -> CXS detail endpoint -> description."""
    m = re.match(r"https://([^/]+)/([^/]+)(/job/.+)$", url)
    if not m:
        return ""
    host, site, path = m.groups()
    tenant = host.split(".")[0]
    code, body, _ = d.fetch(f"https://{host}/wday/cxs/{tenant}/{site}{path}")
    if code != 200:
        return ""
    try:
        return json.loads(body).get("jobPostingInfo", {}).get("jobDescription", "") or ""
    except Exception:  # noqa: BLE001
        return ""


def main() -> int:
    seen = json.load(open(d.SEEN_PATH))

    # Bulk-fetch the boards that hand back descriptions in one call.
    lever_cache, gh_cache = {}, {}
    for url in seen:
        if "jobs.lever.co/" in url:
            tok = url.split("jobs.lever.co/")[1].split("/")[0]
            if tok not in lever_cache:
                lever_cache[tok] = lever_descriptions(tok)
        elif "greenhouse.io/" in url:
            tok = urllib.parse.urlparse(url).path.strip("/").split("/")[0]
            if tok not in gh_cache:
                gh_cache[tok] = greenhouse_descriptions(tok)

    newly, checked, skipped = [], 0, 0
    for url, meta in seen.items():
        title = meta.get("title", "")
        if d.SIE_TAG in title:
            continue  # already tagged
        desc = ""
        if "jobs.lever.co/" in url:
            tok = url.split("jobs.lever.co/")[1].split("/")[0]
            desc = lever_cache.get(tok, {}).get(url, "")
        elif "greenhouse.io/" in url:
            tok = urllib.parse.urlparse(url).path.strip("/").split("/")[0]
            desc = gh_cache.get(tok, {}).get(url, "")
        elif "myworkdayjobs.com" in url:
            desc = workday_description(url)
        else:
            skipped += 1
            continue
        checked += 1
        if desc and SIE_RE.search(desc):
            meta["title"] = title + d.SIE_TAG
            newly.append((title, url))

    print(f"checked {checked} postings ({skipped} on platforms without a "
          f"description endpoint wired here)")
    print(f"newly tagged: {len(newly)}")
    for t, u in newly:
        print(f"  {t}\n    {u}")

    if newly and not DRY:
        json.dump(seen, open(d.SEEN_PATH, "w"), indent=2)
        print("seen_jobs.json updated")
    elif DRY:
        print("(dry run -- nothing written)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
