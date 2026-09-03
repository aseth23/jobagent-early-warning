#!/usr/bin/env python3
"""
Local discovery + verification for Summer 2027 investment internships.

Replaces the cloud routine (which has no internet). Runs on this machine, which
DOES have internet, so every link it posts is one it just loaded live:

  * Greenhouse / Lever / Ashby board APIs return ONLY open postings -> if a job
    is in the response, its link works.
  * A hand-maintained WATCHLIST of specific Workday / tal.net / gr8people / iCIMS
    / Paylocity / Rippling postings is re-fetched each run and dropped when dead.

New live roles are posted to Slack once (deduped in seen_jobs.json).

Config (env):
  SLACK_WEBHOOK_URL   required (or ~/.config/internship-verifier/webhook)
  REPO_DIR            optional (default: this file's dir)
  DRY_RUN=1           print instead of posting / writing
"""
from __future__ import annotations

import json
import os
import re
import sys
import urllib.request
import urllib.error
from datetime import date

REPO_DIR = os.environ.get("REPO_DIR") or os.path.dirname(os.path.abspath(__file__))
SEEN_PATH = os.path.join(REPO_DIR, "seen_jobs.json")
DRY = os.environ.get("DRY_RUN") == "1"
TODAY = date.today().isoformat()

_WF = os.path.expanduser("~/.config/internship-verifier/webhook")
WEBHOOK = os.environ.get("SLACK_WEBHOOK_URL", "").strip()
if not WEBHOOK and os.path.exists(_WF):
    WEBHOOK = open(_WF).read().strip()

UA = {"User-Agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                     "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125 Safari/537.36")}

# ---- firm -> ATS board token -------------------------------------------------
GREENHOUSE = [
    "readystate", "drweng", "virtu", "walleyecapital-external-students",
    "gcmgrosvenor", "point72", "bracebridgecapital", "audaxgroup",
    "roarkcapitalgroup", "theriversidecompany", "financialtechnologypartners",
    "llrpartnersjobs", "harrisassociates", "summitpartnerslp", "generalatlantic",
    "gacampus", "alpineinternships", "bvpanalyst", "leadedgecapitalmanagement",
    "levelequity", "accessholdingsmanagementfirm", "uvimco", "weissassetmanagement",
    "twosigmainvestments", "twosigma", "citadel", "millennium", "balyasny",
    "squarepointcapital", "verition", "worldquant", "sig", "imc", "drwholdings",
    "janestreet", "hudsonrivertrading", "belvederetrading", "geneva-trading",
    "akunacapital", "wolverinetrading", "chicagotrading", "flowtraders",
    "tekionos", "insightpartnersinternship", "battery", "batteryventures",
    "spectrumequity", "jmi", "greathillpartners", "ta-associates", "psgequity",
    "mainsailpartners", "iconiqgrowth", "volitioncapital", "edisonpartners",
    "vistaequitypartners", "thomabravo", "kkr", "carlyle", "apollo",
    "warburgpincus", "silverlake", "hgcapital", "generalcatalyst", "bain",
]
LEVER = [
    "harrisonst", "dadavidson", "raine", "beedie", "point72", "citadel",
    "twosigma", "hudson-river-trading", "voleon", "quantbox", "radix-trading",
    "tower-research-capital", "de-shaw",
]
ASHBY = [
    "volition-capital", "iconiq", "thrivecapital", "ggv", "coatue",
]

# ---- specific postings on ATSes without a clean board API ------------------
WATCHLIST = [
    ("PGIM — 2027 Public Credit Summer Investment Analyst (PAG)", "Newark, NJ",
     "https://pru.wd5.myworkdayjobs.com/wday/cxs/pru/Careers/job/Newark-NJ-USA/PGIM--2027-Public-Credit--Summer-Investment-Analyst-Program--Portfolio-Analysis-Group-_R-124835-2",
     "https://pru.wd5.myworkdayjobs.com/Careers/job/Newark-NJ-USA/PGIM--2027-Public-Credit--Summer-Investment-Analyst-Program--Portfolio-Analysis-Group-_R-124835-2"),
    ("Morgan Stanley — 2027 IM Summer Analyst, Fixed Income", "Boston, MA",
     "https://morganstanley.tal.net/vx/candidate/apply/20903",
     "https://morganstanley.tal.net/vx/candidate/apply/20903"),
    ("Morgan Stanley — 2027 Equity Research Summer Analyst", "New York, NY",
     "https://morganstanley.tal.net/vx/candidate/apply/20783",
     "https://morganstanley.tal.net/vx/candidate/apply/20783"),
    ("BlackRock — 2027 Summer Internship Program, AMERS", "NYC + multiple",
     "https://careers.blackrock.com/job/new-york/2027-summer-internship-program-amers/45831/90628276544",
     "https://careers.blackrock.com/job/new-york/2027-summer-internship-program-amers/45831/90628276544"),
    ("D.E. Shaw — Fundamental Research Analyst Intern (Summer 2027)", "New York, NY",
     "https://www.deshaw.com/careers/fundamental-research-analyst-intern-new-york-summer-2027-5709",
     "https://www.deshaw.com/careers/fundamental-research-analyst-intern-new-york-summer-2027-5709"),
    ("D.E. Shaw — Quantitative Analyst Intern (Summer 2027)", "New York, NY",
     "https://www.deshaw.com/careers/quantitative-analyst-intern-new-york-summer-2027-5890",
     "https://www.deshaw.com/careers/quantitative-analyst-intern-new-york-summer-2027-5890"),
    ("T. Rowe Price — Equity Research Internship (Summer 2027)", "Baltimore, MD",
     "https://troweprice.gr8people.com/jobs/21665/equity-research-internship-opportunity-summer-2027",
     "https://troweprice.gr8people.com/jobs/21665/equity-research-internship-opportunity-summer-2027"),
    ("MLG Capital — 2027 Acquisitions & Capital Team Internship", "Brookfield, WI",
     "https://recruiting.paylocity.com/recruiting/jobs/Details/4428056/MLG-Capital/2027-Acquisitions-Capital-Team-Internship",
     "https://recruiting.paylocity.com/recruiting/jobs/Details/4428056/MLG-Capital/2027-Acquisitions-Capital-Team-Internship"),
    ("Graham Partners — PE Fast Track Two-Year Internship", "Newtown Square, PA",
     "https://ats.rippling.com/graham-partners/jobs/e64f9797-6dde-414d-93ea-58cfa4aa8a2b",
     "https://ats.rippling.com/graham-partners/jobs/e64f9797-6dde-414d-93ea-58cfa4aa8a2b"),
    ("SIG — Credit Analyst Internship: Summer 2027", "Bala Cynwyd, PA",
     "https://careers.sig.com/api/jobs/10794", "https://careers.sig.com/job/10794"),
    ("Affinius Capital — Real Estate Summer Intern 2027", "San Antonio, TX",
     "https://careers-affiniuscapital.icims.com/jobs/2280/job",
     "https://careers-affiniuscapital.icims.com/jobs/2280/job"),
    ("Affinius Capital — Summer 2027 Real Estate Credit Intern", "New York, NY",
     "https://careers-affiniuscapital.icims.com/jobs/2293/job",
     "https://careers-affiniuscapital.icims.com/jobs/2293/job"),
]

INC = re.compile(r"\b(intern|internship|summer analyst|summer associate|"
                 r"co-?op|apprentice)\b", re.I)
INVEST = re.compile(r"(invest|equit|credit|private equity|growth equity|"
                    r"\bventure\b|portfolio|research analyst|quant|capital markets|"
                    r"buyout|secondar|infrastructure|real estate|fixed income|"
                    r"\bmacro\b|trading|\bdeal|diligence|\banalyst\b)", re.I)
# require the role to NOT be an old cycle / senior / grad-only; 2027 in the title optional
EXCLUDE = re.compile(r"(\bsenior\b|vice president|\bvp\b|\bdirector\b|principal|"
                     r"\bmanager\b|\blead\b|\bstaff\b|head of|\b202[0-6]\b|"
                     r"\bmba\b|ph\.?d|master('?s| or)|doctoral|full[- ]time|"
                     r"new grad|experienced)", re.I)

# skip clearly non-US postings unless a US city is also listed
FOREIGN = re.compile(r"(singapore|london|dublin|ireland|hong kong|japan|tokyo|"
                     r"\bparis\b|beijing|shanghai|shenzhen|hanoi|ho chi minh|"
                     r"madrid|brussels|amsterdam|sydney|toronto|montreal|mumbai|"
                     r"bengaluru|bangalore|seoul|zurich|munich|frankfurt|milan|"
                     r"\bindia\b|\buk\b|\bemea\b)", re.I)
US = re.compile(r"(new york|\bnyc\b|chicago|boston|san francisco|\bsf\b|los angeles|"
                r"\bla\b|miami|austin|houston|dallas|charlotte|atlanta|seattle|"
                r"greenwich|stamford|philadelphia|baltimore|washington|\bdc\b|"
                r"newark|princeton|connecticut|\bct\b|new jersey|\bnj\b|texas|"
                r"\btx\b|florida|\bfl\b|illinois|\bil\b|california|\bca\b|\bma\b|"
                r"\bny\b|\bpa\b|\bwi\b|\bmd\b|united states|u\.s\.|remote - us|"
                r"denver|minneapolis|nashville|richmond|mclean|wilmington)", re.I)


def us_ok(loc: str) -> bool:
    if not loc:
        return True  # unknown location -> keep, don't silently drop
    if US.search(loc):
        return True
    return not FOREIGN.search(loc)


def fetch(url, timeout=15):
    try:
        r = urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout)
        return r.status, r.read(200000).decode("utf-8", "replace"), r.geturl()
    except urllib.error.HTTPError as e:
        return e.code, "", url
    except Exception as e:  # noqa: BLE001
        return None, f"{type(e).__name__}: {e}", url


def want(title: str) -> bool:
    return bool(INC.search(title) and INVEST.search(title)
               and not EXCLUDE.search(title))


def from_greenhouse(token):
    code, body, _ = fetch(f"https://boards-api.greenhouse.io/v1/boards/{token}/jobs")
    if code != 200:
        return []
    try:
        jobs = json.loads(body).get("jobs", [])
    except Exception:  # noqa: BLE001
        return []
    out = []
    for j in jobs:
        t = j.get("title", "")
        loc = (j.get("location") or {}).get("name", "")
        if want(t) and us_ok(loc):
            out.append((t, loc, j["absolute_url"]))
    return out


def from_lever(token):
    code, body, _ = fetch(f"https://api.lever.co/v0/postings/{token}?mode=json")
    if code != 200:
        return []
    try:
        posts = json.loads(body)
    except Exception:  # noqa: BLE001
        return []
    out = []
    for p in posts:
        t = p.get("text", "")
        loc = (p.get("categories") or {}).get("location", "")
        if want(t) and us_ok(loc):
            out.append((t, loc, p["hostedUrl"]))
    return out


def from_ashby(token):
    code, body, _ = fetch(
        f"https://api.ashbyhq.com/posting-api/job-board/{token}?includeCompensation=false")
    if code != 200:
        return []
    try:
        posts = json.loads(body).get("jobs", [])
    except Exception:  # noqa: BLE001
        return []
    out = []
    for p in posts:
        t = p.get("title", "")
        loc = p.get("location", "")
        if want(t) and us_ok(loc):
            out.append((t, loc, p.get("jobUrl", "")))
    return out


def watch_live(check_url: str) -> bool:
    code, body, final = fetch(check_url)
    if code in (404, 410):
        return False
    if code != 200:
        return False
    low = body.lower()
    if any(m in low for m in ("no longer accepting", "position has been filled",
                              "this job is no longer", "job was removed",
                              "posting is not available", "error=true")):
        return False
    if re.search(r"[?&]error=true", final):
        return False
    return True


def main() -> int:
    if not WEBHOOK and not DRY:
        print("no SLACK_WEBHOOK_URL", file=sys.stderr)
        return 2

    seen = {}
    if os.path.exists(SEEN_PATH):
        try:
            seen = json.load(open(SEEN_PATH))
        except Exception:  # noqa: BLE001
            seen = {}

    found: list[tuple[str, str, str]] = []
    for tok in GREENHOUSE:
        found += [(f"{tok}: {t}", l, u) for t, l, u in from_greenhouse(tok)]
    for tok in LEVER:
        found += [(f"{tok}: {t}", l, u) for t, l, u in from_lever(tok)]
    for tok in ASHBY:
        found += [(f"{tok}: {t}", l, u) for t, l, u in from_ashby(tok)]

    watch_ok, watch_dead = [], []
    for label, loc, chk, pub in WATCHLIST:
        (watch_ok if watch_live(chk) else watch_dead).append((label, loc, pub))

    new = [(t, l, u) for (t, l, u) in found if u not in seen]
    for t, l, u in new:
        seen[u] = {"title": t, "first_seen": TODAY}
    # keep watchlist live ones in seen too (so they aren't "new" every run)
    fresh_watch = [(lab, loc, pub) for lab, loc, pub in watch_ok if pub not in seen]
    for lab, loc, pub in fresh_watch:
        seen[pub] = {"title": lab, "first_seen": TODAY}

    if not DRY:
        json.dump(seen, open(SEEN_PATH, "w"), indent=2)

    if not new and not fresh_watch:
        print(f"no new roles ({len(found)} board hits, {len(watch_ok)} watchlist live).")
        return 0

    lines = [f":mag: {len(new) + len(fresh_watch)} new live internship(s) — "
             f"links checked {TODAY}"]
    for t, l, u in sorted(new):
        lines.append(f"• {t}{f' ({l})' if l else ''}\n  {u}")
    for lab, loc, pub in fresh_watch:
        lines.append(f"• {lab}{f' ({loc})' if loc else ''}\n  {pub}")
    text = "\n".join(lines)

    if DRY:
        print(text)
        return 0
    urllib.request.urlopen(urllib.request.Request(
        WEBHOOK, data=json.dumps({"text": text}).encode(),
        headers={"Content-Type": "application/json"}), timeout=20).read()
    print(f"posted {len(new) + len(fresh_watch)} new roles.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
