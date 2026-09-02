#!/usr/bin/env python3
"""
Local link-verifier for the growth-equity internship early-warning routine.

The cloud discovery routine has no network access, so it logs candidates to
early_warning_state.json with verification_status "UNCHECKED". This script runs
on a machine that HAS internet, checks every unchecked link for real, writes the
verdict back to the ledger, and posts a Slack digest with only the live roles.

Run it a few minutes after each routine run (see the launchd plist).

Config (environment variables):
  SLACK_WEBHOOK_URL   required - Slack incoming webhook for #internship-search-alerts
  REPO_DIR            optional - path to the repo (default: this file's directory)
  GIT_SYNC           optional - "1" (default) to git pull before / commit+push after
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import urllib.request
import urllib.error
import urllib.parse
from datetime import date

REPO_DIR = os.environ.get("REPO_DIR") or os.path.dirname(os.path.abspath(__file__))
LEDGER = os.path.join(REPO_DIR, "early_warning_state.json")

_WEBHOOK_FILE = os.path.expanduser("~/.config/internship-verifier/webhook")
WEBHOOK = os.environ.get("SLACK_WEBHOOK_URL", "").strip()
if not WEBHOOK and os.path.exists(_WEBHOOK_FILE):
    with open(_WEBHOOK_FILE) as _f:
        WEBHOOK = _f.read().strip()
GIT_SYNC = os.environ.get("GIT_SYNC", "1") == "1"
TODAY = date.today().isoformat()

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
      "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0 Safari/537.36")

# University career-hub mirrors + job aggregators. A 200 from these means nothing
# about whether the underlying posting is still open, so we never call them LIVE.
MIRROR_HOSTS = (
    "careers.kelley.iu.edu", "career.cornell.edu", "careerhub.students.duke.edu",
    "careerservices.", "careercenter.", "careers.amherst.edu", "careers.uw.edu",
    "connections.villanova.edu", "capd.mit.edu", "ocs.yale.edu", "capd.mit.edu",
    "careers.rhsmith.umd.edu", "elevate.iit.edu", "career.ucla.edu",
    "careerdevelopment.morehouse.edu", "harvardvarsityclub.org",
    ".edu/jobs", "builtin.com", "builtinnyc.com", "builtinboston.com",
    "builtinchicago.org", "ziprecruiter.com", "linkedin.com", "simplify.jobs",
    "talent.com", "talents.vaia.com", "wallstreetfriends.org", "jobs.anitab.org",
    "econugblog.wordpress.com", "canarywharfian.co.uk", "intern-list.com",
    "selectleaders.com", "themuse.com", "prosple.com", "adzuna.com", "indeed.com",
    "glassdoor.com", "jobright.ai", "bebee.com", "adventiscg.com", "grabjobs.co",
    "tealhq.com", "joinrunway.io", "applyblast.com", "jobrapido.com", "jobleads.com",
    "heysuccess.com", "weekday.works", "extern.com", "finbound.org",
    "growthequityinterviewguide.com", "the-trackr.com", "interninsider.me",
    "haystackapp.io", "joinhandshake.com", "startup.jobs", "wellfound.com",
    "getsmartresume.com", "jobrapido", "ourcareerplace", "opportunitiesforyouth",
    "scholarships.af", "kabulscholarship", "skillsire.com", "jobs.wallstreet",
)

# Direct-from-employer ATS URL shapes we can actually verify.
ATS_HOSTS = ("job-boards.greenhouse.io", "boards.greenhouse.io", "jobs.lever.co",
             "myworkdayjobs.com", "jobs.ashbyhq.com", ".icims.com", "gr8people.com",
             "careers.sig.com", "deshaw.com/careers", "ats.rippling.com",
             "recruiting.paylocity.com", "apply.workable.com", "eightfold.ai")

# statuses we skip: already resolved, or intentionally parked by the routine
SKIP_STATUS = {"LIVE", "DEAD", "APPLIED", "CLOSED", "ALREADY_REPORTED", "CARRIED_OVER"}


def run_git(*args: str) -> str:
    return subprocess.run(["git", "-C", REPO_DIR, *args],
                          capture_output=True, text=True).stdout.strip()


def fetch(url: str, timeout: int = 20):
    """Return (status_code, final_url, body_snippet) or (None, None, err) on failure."""
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            body = r.read(400000).decode("utf-8", "replace")
            return r.status, r.geturl(), body
    except urllib.error.HTTPError as e:
        return e.code, url, ""
    except Exception as e:  # noqa: BLE001
        return None, None, f"{type(e).__name__}: {e}"


def classify(url: str, title: str = "") -> tuple[str, str]:
    """Return (verdict, note). verdict in LIVE / DEAD / UNREACHABLE."""
    if not url or not url.startswith("http"):
        return "UNREACHABLE", "no usable URL"

    # Greenhouse: query the single job on the board API (200 = live, 404 = gone)
    if "greenhouse.io" in url:
        m = re.search(r"greenhouse\.io/(?:embed/job_app\?token=|([^/?]+)/jobs/)(\d+)", url)
        if m and m.group(1):
            token, job_id = m.group(1), m.group(2)
            code, _, _ = fetch(
                f"https://boards-api.greenhouse.io/v1/boards/{token}/jobs/{job_id}")
            if code == 200:
                return "LIVE", "greenhouse job API returns 200"
            if code in (404, 410):
                return "DEAD", f"greenhouse job API returns {code}"
        else:
            return "UNREACHABLE", "greenhouse board root only - no specific job id"

    # SIG: careers.sig.com 404s bots on /job/<id>; its search API needs a keyword.
    m = re.search(r"careers\.sig\.com/job/(\d+)", url)
    if m:
        req_id = m.group(1)
        kw = urllib.parse.quote((title or "internship summer 2027")[:60])
        code, _, body = fetch(f"https://careers.sig.com/api/jobs?keywords={kw}&limit=100")
        if code == 200 and body.lstrip().startswith("{"):
            try:
                ids = {str(j.get("data", {}).get("req_id"))
                       for j in json.loads(body).get("jobs", [])}
                return ("LIVE", "SIG search API lists this req id") if req_id in ids \
                    else ("DEAD", "SIG search API no longer lists this req id")
            except Exception:  # noqa: BLE001
                pass
        return "UNREACHABLE", "SIG careers site blocks automated checks - verify by hand"

    # Lever: query the single posting (200 = live, 404 = gone)
    if "lever.co" in url:
        m = re.search(r"lever\.co/([^/]+)/([0-9a-f-]{36})", url)
        if m:
            token, pid = m.group(1), m.group(2)
            code, _, _ = fetch(f"https://api.lever.co/v0/postings/{token}/{pid}")
            if code == 200:
                return "LIVE", "lever posting API returns 200"
            if code in (404, 410):
                return "DEAD", f"lever posting API returns {code}"
        else:
            return "UNREACHABLE", "lever board root only - no specific posting id"

    # University mirrors / aggregators: a 200 tells us nothing - don't guess LIVE.
    if any(h in url for h in MIRROR_HOSTS):
        return "UNREACHABLE", "only a mirror/aggregator link - needs the real ATS URL"

    # Generic fetch + heuristics
    code, final, body = fetch(url)
    if code is None:
        return "UNREACHABLE", final or "fetch failed"
    if code in (404, 410):
        return "DEAD", f"HTTP {code}"
    low = (body or "").lower()
    dead_markers = ("no longer accepting applications", "position has been filled",
                    "this job is no longer available", "job was removed",
                    "posting is not available", "error=true", "sorry, this job",
                    "no longer available", "this position is closed")
    if any(mk in low for mk in dead_markers):
        return "DEAD", "page says the posting is closed/removed"
    if final and re.search(r"[?&]error=true", final):
        return "DEAD", "redirected to board error page"
    if code == 200:
        # a bare company careers page (no job id / job path) proves nothing
        path = re.sub(r"https?://[^/]+", "", final or url)
        if "/job" not in path.lower() and not re.search(r"\d{4,}", path):
            return "UNREACHABLE", "company careers page, not a specific posting"
        return "LIVE", "HTTP 200, no closed/removed markers"
    return "UNREACHABLE", f"HTTP {code}"


def candidate_urls(entry: dict) -> list[str]:
    urls: list[str] = []
    for key in ("official_application_url", "url", "apply_url"):
        v = entry.get(key)
        if isinstance(v, str):
            urls.append(v.split(" ")[0].strip())
    v = entry.get("urls")
    if isinstance(v, list):
        urls.extend(str(x).split(" ")[0].strip() for x in v)
    # employer-direct ATS first, mirrors/aggregators last
    def rank(u: str) -> int:
        if any(h in u for h in MIRROR_HOSTS):
            return 90
        if any(h in u for h in ATS_HOSTS):
            return 0
        if "/job" in u or "/careers/" in u or "careers." in u:
            return 10
        return 20
    seen, out = set(), []
    for u in sorted((u for u in urls if u.startswith("http")), key=rank):
        if u not in seen:
            seen.add(u)
            out.append(u)
    return out


def main() -> int:
    if not WEBHOOK:
        print("SLACK_WEBHOOK_URL not set - aborting.", file=sys.stderr)
        return 2
    if not os.path.exists(LEDGER):
        print(f"ledger not found: {LEDGER}", file=sys.stderr)
        return 2

    if GIT_SYNC:
        run_git("pull", "--rebase", "--autostash")

    with open(LEDGER) as f:
        ledger = json.load(f)

    live, dead, unreachable = [], [], []

    for key, entry in ledger.items():
        if not isinstance(entry, dict):
            continue
        status = str(entry.get("verification_status") or entry.get("status") or "").upper()
        if status in SKIP_STATUS:
            continue
        if entry.get("verify_alerted"):
            continue

        urls = candidate_urls(entry)
        parts = key.split("|")
        company = entry.get("company") or (parts[0].replace("_", " ").title() if parts else key)
        role = (entry.get("title") or entry.get("role")
                or (parts[1].replace("_", " ") if len(parts) > 1 else key))
        loc = entry.get("location") or (parts[2] if len(parts) > 2 else "")
        if loc.lower().startswith(("not confirmed", "multiple", "us ", "united states")):
            loc = ""

        verdict, note, used_url = "UNREACHABLE", "no URL found", ""
        for u in urls:
            verdict, note = classify(u, str(role))
            used_url = u
            if verdict in ("LIVE", "DEAD"):
                break

        entry["verification_status"] = verdict if verdict != "UNREACHABLE" else "UNCHECKED"
        entry["verify_note"] = f"{note} (checked {TODAY})"
        if verdict == "LIVE":
            entry["official_application_url"] = used_url
            entry["verify_alerted"] = True
            live.append((company, role, loc, used_url))
        elif verdict == "DEAD":
            entry["verify_alerted"] = True
            dead.append((company, role))
        else:
            unreachable.append((company, role, used_url))

    dry = os.environ.get("DRY_RUN") == "1"
    if not dry:
        with open(LEDGER, "w") as f:
            json.dump(ledger, f, indent=2)
            f.write("\n")

    def sync():
        if not dry and GIT_SYNC and run_git("status", "--porcelain"):
            run_git("add", "early_warning_state.json")
            run_git("commit", "-m", f"verify: {len(live)} live / {len(dead)} dead ({TODAY})")
            run_git("push")

    if not (live or dead):
        print(f"nothing definitive to report ({len(unreachable)} unreachable).")
        sync()
        return 0

    lines = [f":white_check_mark: Link check {TODAY} — {len(live)} live, {len(dead)} dead"]
    if live:
        lines.append("\n*Live — apply:*")
        for c, r, l, u in live:
            lines.append(f"• {c} — {r}{f' ({l})' if l else ''} — {u}")
    if dead:
        lines.append("\n*Dead / closed — skip:*")
        for c, r in dead:
            lines.append(f"• {c} — {r}")
    if unreachable:
        shown = unreachable[:6]
        lines.append(f"\n*No verifiable link ({len(unreachable)}) — routine only has a mirror/aggregator URL:*")
        for c, r, u in shown:
            lines.append(f"• {c} — {r}")
        if len(unreachable) > len(shown):
            lines.append(f"• …+{len(unreachable) - len(shown)} more (in early_warning_state.json)")

    text = "\n".join(lines)
    if os.environ.get("DRY_RUN") == "1":
        print("--- DRY RUN, would post to Slack: ---\n" + text)
        return 0

    payload = json.dumps({"text": text}).encode()
    req = urllib.request.Request(WEBHOOK, data=payload,
                                headers={"Content-Type": "application/json"})
    try:
        urllib.request.urlopen(req, timeout=20).read()
        print(f"posted: {len(live)} live, {len(dead)} dead, {len(unreachable)} unreachable")
    except Exception as e:  # noqa: BLE001
        print(f"slack post failed: {e}", file=sys.stderr)
        return 1

    sync()
    return 0


if __name__ == "__main__":
    sys.exit(main())
