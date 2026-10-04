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

import html
import json
import os
import re
import signal
import sys
import time
import urllib.request
import urllib.error
from collections import defaultdict
from datetime import date, datetime

REPO_DIR = os.environ.get("REPO_DIR") or os.path.dirname(os.path.abspath(__file__))
SEEN_PATH = os.path.join(REPO_DIR, "seen_jobs.json")
DRY = os.environ.get("DRY_RUN") == "1"
# Hourly supplementary run: only post postings that mention the SIE exam,
# and -- critically -- only mark THOSE as seen. A non-SIE posting found
# during an SIE_ONLY run must stay unseen so the regular full run still
# catches and posts it normally; this run is additive, not a replacement.
SIE_ONLY = os.environ.get("SIE_ONLY") == "1"
TODAY = date.today().isoformat()

_WF = os.path.expanduser("~/.config/internship-verifier/webhook")
WEBHOOK = os.environ.get("SLACK_WEBHOOK_URL", "").strip()
if not WEBHOOK and os.path.exists(_WF):
    WEBHOOK = open(_WF).read().strip()

UA = {"User-Agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                     "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125 Safari/537.36")}

# Defined early so WATCHLIST entries (below) can embed it directly for firms
# manually confirmed to mention the SIE exam, same as sie_tag() applies
# automatically for description-checked sources.
SIE_TAG = " \U0001F3AF[SIE mentioned]"

# ---- firm -> ATS board token -------------------------------------------------
GREENHOUSE = [
    "readystate", "drweng", "virtu", "walleyecapital-external-students",
    "gcmgrosvenor", "point72", "bracebridgecapital", "audaxgroup",
    "roarkcapitalgroup", "theriversidecompany", "financialtechnologypartners",
    "llrpartnersjobs", "harrisassociates", "summitpartnerslp", "generalatlantic",
    "gacampus", "alpineinternships", "bvpanalyst", "leadedgecapitalmanagement",
    "levelequity", "accessholdingsmanagementfirm", "uvimco", "weissassetmanagement",
    "citadel", "millennium", "balyasny",
    "squarepointcapital", "verition", "worldquant", "sig", "imc", "drwholdings",
    "janestreet", "genevatrading",
    "akunacapital", "xtxmarketstechnologies", "optiverus", "jumptrading",
    "towerresearchcapital",
    "wolverinetrading", "chicagotrading", "flowtraders",
    "tekionos", "insightpartnersinternship", "battery", "batteryventures",
    "spectrumequity", "jmi", "greathillpartners", "ta-associates", "psgequity",
    "mainsailpartners", "iconiqgrowth", "volitioncapital", "edisonpartners",
    "vistaequitypartners", "thomabravo", "kkr", "carlyle", "apollo",
    "warburgpincus", "silverlake", "hgcapital", "generalcatalyst", "bain",
    "tpgcareers", "aquaticcapitalmanagement",
    # long-only / fundamental asset management, equity & fixed-income research
    "aqr", "stepstone", "williamblair", "artisanpartners", "baroncapital",
    "adamsstreetpartners", "mangroup",
    # Miami / Florida finance hub + more PE / hedge funds
    "summeranalyst", "isquaredcapital", "schonfeld", "exoduspoint", "pointstate",
    "valorequitypartners", "pantheon", "americansecurities", "gtcr",
    "audaxprivateequity", "hig", "trivest", "comvestpartners", "starwoodcapital",
    "kayneanderson", "bayviewassetmanagement", "citadel", "millennium",
    "balyasny", "verition", "hbk", "elliottmanagement", "d1capital",
    "solomonpartnersstudentsgraduates", "lincolninternational",
]
LEVER = [
    "harrisonst", "dadavidson", "raine", "beedie", "point72", "citadel",
    "hudson-river-trading", "voleon", "quantbox", "radix-trading",
    "de-shaw", "thomabravo", "hig", "starwood",
    "millennium", "exoduspoint", "schonfeld", "verition", "txse",
]
ASHBY = [
    "volition-capital", "iconiq", "thrivecapital", "ggv", "coatue",
]
# ATS token -> readable firm name for the digest
NAMES = {
    "summeranalyst": "I Squared Capital", "isquaredcapital": "I Squared Capital",
    "drweng": "DRW", "bvpanalyst": "Bessemer Venture Partners",
    "walleyecapital-external-students": "Walleye Capital",
    "leadedgecapitalmanagement": "Lead Edge Capital", "harrisonst": "Harrison Street",
    "dadavidson": "D.A. Davidson", "de-shaw": "D.E. Shaw", "aqr": "AQR",
    "gcmgrosvenor": "GCM Grosvenor", "financialtechnologypartners": "FT Partners",
    "roarkcapitalgroup": "Roark Capital", "theriversidecompany": "The Riverside Company",
    "llrpartnersjobs": "LLR Partners", "harrisassociates": "Harris Associates / Oakmark",
    "summitpartnerslp": "Summit Partners", "gacampus": "General Atlantic",
    "generalatlantic": "General Atlantic", "adamsstreetpartners": "Adams Street Partners",
    "mangroup": "Man Group", "neubergerberman": "Neuberger Berman",
    "wellingtonmanagement": "Wellington Management", "gqgpartners": "GQG Partners",
    "diamondhillcapital": "Diamond Hill", "aresmanagement": "Ares Management",
    "oaktreecapital": "Oaktree", "blueowlcapital": "Blue Owl", "sixthstreet": "Sixth Street",
    "partnersgroup": "Partners Group", "valorequitypartners": "Valor Equity Partners",
    "americansecurities": "American Securities", "gtcr": "GTCR",
    "audaxprivateequity": "Audax Private Equity", "hig": "H.I.G. Capital",
    "starwoodcapital": "Starwood Capital", "starwood": "Starwood Capital",
    "kayneanderson": "Kayne Anderson", "bayviewassetmanagement": "Bayview Asset Management",
    "thomabravo": "Thoma Bravo", "d1capital": "D1 Capital", "hbk": "HBK Capital",
    "solomonpartnersstudentsgraduates": "Solomon Partners",
    "lincolninternational": "Lincoln International",
    "elliottmanagement": "Elliott Management", "exoduspoint": "ExodusPoint",
    "pointstate": "PointState Capital", "schonfeld": "Schonfeld", "verition": "Verition",
    "citadel": "Citadel", "millennium": "Millennium", "balyasny": "Balyasny",
    "trivest": "Trivest Partners", "comvestpartners": "Comvest Partners",
    "pantheon": "Pantheon", "williamblair": "William Blair", "artisanpartners": "Artisan Partners",
    "baroncapital": "Baron Capital", "virtu": "Virtu Financial", "worldquant": "WorldQuant",
    "flowtraders": "Flow Traders", "akunacapital": "Akuna Capital", "stepstone": "StepStone",
    "raine": "The Raine Group", "beedie": "Beedie Capital", "point72": "Point72",
    "hudson-river-trading": "Hudson River Trading",
    "towerresearchcapital": "Tower Research Capital", "voleon": "Voleon Group",
    "tpgcareers": "TPG", "aquaticcapitalmanagement": "Aquatic Capital Management",
    "txse": "Texas Stock Exchange (TXSE)", "genevatrading": "Geneva Trading",
    "janestreet": "Jane Street", "imc": "IMC Trading",
    "xtxmarketstechnologies": "XTX Markets", "optiverus": "Optiver",
    "jumptrading": "Jump Trading",
}
# Workday: (label, host, tenant, site) — the CXS /jobs search returns only open reqs,
# so anything it returns has a working link. Covers banks in secondary US markets
# (Charlotte, Chicago, the Southeast) that don't use Greenhouse/Lever.
WORKDAY = [
    ("Truist", "truist.wd1.myworkdayjobs.com", "truist", "Careers"),
    ("Wells Fargo", "wf.wd1.myworkdayjobs.com", "wf", "WellsFargoJobs"),
    ("BMO", "bmo.wd3.myworkdayjobs.com", "bmo", "External"),
    ("Baird", "baird.wd1.myworkdayjobs.com", "baird", "Careers"),
    ("KeyBank", "keybank.wd5.myworkdayjobs.com", "keybank", "External_Career_Site"),
    ("Regions", "regions.wd5.myworkdayjobs.com", "regions", "Regions_Careers"),
    ("PNC", "pnc.wd5.myworkdayjobs.com", "pnc", "External"),
    ("Blackstone", "blackstone.wd1.myworkdayjobs.com", "blackstone",
     "Blackstone_Campus_Careers"),
    ("Barings", "barings.wd1.myworkdayjobs.com", "barings", "Barings"),
    # (Prudential/PGIM is listed once further down -- this duplicate of the
    # same tenant+site was scanning the identical board twice every run.)
    ("Fifth Third", "fifththird.wd5.myworkdayjobs.com", "fifththird", "53careers"),
    ("Citi", "citi.wd5.myworkdayjobs.com", "citi", "2"),
    # "RaymondJamesCareers" is their experienced-hire board and returns 0
    # student roles -- the campus postings live on a separate site. Same
    # trap as AllianceBernstein's dead "alliancebernsteincareers" slug.
    ("Raymond James", "raymondjames.wd1.myworkdayjobs.com", "raymondjames",
     "RaymondJamesEarlyCareers"),
    ("Dimensional Fund Advisors", "dimensional.wd5.myworkdayjobs.com",
     "dimensional", "DFA_Careers"),
    ("Ares Management", "aresmgmt.wd1.myworkdayjobs.com", "aresmgmt", "External", True),
    # "External" is the experienced-hire board (0 postings); all 22 of their
    # student roles sit on "Campus".
    ("Houlihan Lokey", "hl.wd1.myworkdayjobs.com", "hl", "Campus"),
    ("American Century Investments", "americancentury.wd5.myworkdayjobs.com",
     "americancentury", "AmericanCenturyInvestments", True),
    ("TD Bank", "td.wd3.myworkdayjobs.com", "td", "TD_Bank_Careers"),
    ("Northern Trust", "ntrs.wd1.myworkdayjobs.com", "ntrs", "northerntrust"),
    # "alliancebernsteincareers" (the original site slug here) is a dead/empty
    # board -- always returns 0 jobs. The real, active campus board is
    # "abcampuscareers", found 2026-09-29 from a user-supplied posting link.
    ("AllianceBernstein", "abglobal.wd1.myworkdayjobs.com", "abglobal",
     "abcampuscareers"),
    ("Invesco", "invesco.wd1.myworkdayjobs.com", "invesco", "IVZ"),
    ("Neuberger Berman", "nb.wd1.myworkdayjobs.com", "nb", "NBCareers"),
    ("Leerink Partners", "leerink.wd5.myworkdayjobs.com", "leerink", "leerinkpartners"),
    ("BRG (Berkeley Research Group)", "thinkbrg.wd5.myworkdayjobs.com",
     "thinkbrg", "BRG_External_Career_Site"),
    # Exchanges themselves -- wherever one sits, banks cluster nearby (Chicago
    # for CME/Cboe, Atlanta for ICE, Dallas for TXSE). No 2027 postings live
    # yet on either as of this add; wired in so they're caught same-day.
    ("CME Group", "cmegroup.wd1.myworkdayjobs.com", "cmegroup", "cme_careers"),
    ("Cboe Global Markets", "cboe.wd1.myworkdayjobs.com", "cboe", "External_Career_CBOE"),
    # Boston: major asset-management hub (also home to the BOX options exchange)
    ("MFS Investment Management", "mfs.wd1.myworkdayjobs.com", "mfs", "MFS-Careers"),
    ("State Street", "statestreet.wd1.myworkdayjobs.com", "statestreet", "Global"),
    # Sourced from a campus career-fair company list (2026-09-17).
    ("CIBC", "cibc.wd3.myworkdayjobs.com", "cibc", "campus"),
    ("Prudential / PGIM", "pru.wd5.myworkdayjobs.com", "pru", "Careers"),
    ("RBC", "rbc.wd3.myworkdayjobs.com", "rbc", "RBCEARLYTALENT1"),
    # Big well-known index/asset-management names the user asked for by name.
    ("S&P Global", "spgi.wd5.myworkdayjobs.com", "spgi", "spgi_careers"),
    ("Vanguard", "vanguard.wd5.myworkdayjobs.com", "vanguard", "vanguard_external"),
    # Elite boutique IBs, sourced from an "already applied to some of these,
    # find me more" request.
    ("PJT Partners", "pjtpartners.wd1.myworkdayjobs.com", "pjtpartners", "Students"),
    ("Piper Sandler", "pipersandler.wd501.myworkdayjobs.com", "pipersandler",
     "Piper_Sandler_Careers"),
    # "go find new companies" sweep (2026-09-28).
    ("Barclays", "barclays.wd3.myworkdayjobs.com", "barclays",
     "External_Career_Site_Barclays"),
    # Harris Williams is a PNC subsidiary and posts on PNC's own Workday tenant.
    ("Harris Williams", "pnc.wd5.myworkdayjobs.com", "pnc", "HarrisWilliams"),
    ("Capital Group", "capgroup.wd1.myworkdayjobs.com", "capgroup",
     "capitalgroupcareers"),
    # User already passed the SIE and wants US broker-dealer / wealth
    # roles specifically -- these two explicitly reference it (LPL's
    # Wealth Advisory Group intern track has interns sit for the SIE;
    # Ameriprise's branch network does the same for its advisor interns).
    ("LPL Financial", "lplfinancial.wd1.myworkdayjobs.com", "lplfinancial", "University"),
    ("Ameriprise", "ameriprise.wd5.myworkdayjobs.com", "ameriprise", "Ameriprise"),
    # Vault 2026 Most Prestigious Banking Firms cross-reference (2026-09-29).
    ("Guggenheim Securities", "guggenheim.wd1.myworkdayjobs.com", "guggenheim",
     "Guggenheim_Careers_Campus"),
    ("Deutsche Bank", "db.wd3.myworkdayjobs.com", "db", "DBWebsite"),
    # Regional banks + TIAA/Nuveen (2026-10-02 sweep).
    ("US Bank", "usbank.wd1.myworkdayjobs.com", "usbank", "US_Bank_Careers"),
    ("Huntington", "huntington.wd12.myworkdayjobs.com", "huntington", "HNBcareers"),
    ("M&T Bank", "mtb.wd5.myworkdayjobs.com", "mtb", "Campus"),
    # NOTE: TIAA/Nuveen titles its internship cohort "20XX Early Talent
    # Rotational Program" with no "intern"/"internship" word anywhere in the
    # title, so it doesn't match INC even though the underlying program is a
    # real 10-week undergrad summer internship. Wired in anyway for whatever
    # non-rotational-program postings it does catch; the rotational-program
    # titles are a known, disclosed gap, not a silent miss.
    ("TIAA/Nuveen", "tiaa.wd1.myworkdayjobs.com", "tiaa", "Search"),
    ("Brookfield", "brookfield.wd5.myworkdayjobs.com", "brookfield", "brookfield"),
    # Texas Capital Bank's one Summer Analyst posting is titled generically
    # ("2027 Summer Analyst (Internship)", no department named) but its
    # description is credit analysis / commercial banking / transaction
    # structuring -- the bank's whole business, not a side function. Same
    # reasoning as Ares/American Century: bypass the INVEST keyword check.
    ("Texas Capital Bank", "texascapitalbank.wd12.myworkdayjobs.com",
     "texascapitalbank", "Careers", True),
    # Found via a broad myworkdayjobs.com-scoped search across the user's
    # interest categories rather than researching one firm at a time
    # (2026-10-03).
    ("Arrowstreet Capital", "arrowstreetcapital.wd5.myworkdayjobs.com",
     "arrowstreetcapital", "Campus_Careers"),
    ("JLL", "jll.wd1.myworkdayjobs.com", "jll", "jllcareers"),
    # NOTE: NY Fed's own board ("rb.wd5.myworkdayjobs.com/FRS") also covers
    # several other regional Federal Reserve Banks (St. Louis postings show
    # up on the same tenant). Their flagship "Markets Group" internship
    # (open-market-operations desk -- exactly the kind of role the user
    # wants) doesn't match INVEST because the title only says "Markets
    # Group", not "capital markets"/"global markets". Not broadening INVEST
    # for one tenant's naming quirk; "Research Group" postings still match.
    ("Federal Reserve", "rb.wd5.myworkdayjobs.com", "rb", "FRS"),
    # Found via a Handshake public-posting search (2026-10-04).
    ("Western Alliance Bank", "westernalliancebank.wd5.myworkdayjobs.com",
     "westernalliancebank", "WAB"),
    # Earlier "capitalone" guess for the Workday portal was never verified;
    # real tenant found via the login-page redirect on capitalonecareers.com.
    ("Capital One", "capitalone.wd12.myworkdayjobs.com", "capitalone", "Capital_One"),
]

# Roles like the user wants front-and-centre: bank / IB / credit / equity research /
# wealth / PE / AM summer-analyst internships. These sort to the top of the digest.
PRIORITY = re.compile(
    r"(investment bank|\bib\b|summer analyst|credit analyst|equity research|"
    r"wealth manage|asset manage|private equity|capital markets|"
    r"portfolio|research analyst|investment analyst|sales & trading|"
    r"sales and trading|corporate banking|commercial bank|real estate capital|"
    r"investment intern|securities)", re.I)

# ---- specific postings on ATSes without a clean board API ------------------
WATCHLIST = [
    # UBS runs on Taleo (jobs.ubs.com/TGnewUI/...) -- not a platform with a
    # clean JSON API like the others, so this specific user-found posting is
    # watchlisted individually rather than built out as a full scraper.
    (f"UBS — 2027 Summer Internship Program, Wealth Advice Center{SIE_TAG}", "Weehawken, NJ",
     "https://jobs.ubs.com/TGnewUI/Search/home/HomeWithPreLoad?PageType=JobDetails&jobid=350294&partnerid=25008&siteid=5131",
     "https://jobs.ubs.com/TGnewUI/Search/home/HomeWithPreLoad?PageType=JobDetails&jobid=350294&partnerid=25008&siteid=5131"),
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
    ("Affinius Capital — Real Estate Summer Intern 2027", "San Antonio, TX",
     "https://careers-affiniuscapital.icims.com/jobs/2280/job",
     "https://careers-affiniuscapital.icims.com/jobs/2280/job"),
    ("Affinius Capital — Summer 2027 Real Estate Credit Intern", "New York, NY",
     "https://careers-affiniuscapital.icims.com/jobs/2293/job",
     "https://careers-affiniuscapital.icims.com/jobs/2293/job"),
    ("Group One Trading — Trading Analyst Intern", "Chicago, IL",
     "https://group1.applicantpro.com/jobs/3859850",
     "https://group1.applicantpro.com/jobs/3859850"),
    ("Group One Trading — Trading Analyst Intern", "New York, NY",
     "https://www.applicantpro.com/openings/group1/jobs/2002537/NY-New-York/New-York/Trading-Analyst-Intern",
     "https://www.applicantpro.com/openings/group1/jobs/2002537/NY-New-York/New-York/Trading-Analyst-Intern"),
    ("Moelis & Company — 2027 Summer Analyst, Investment Banking", "New York, NY",
     "https://moelis-careers.tal.net/vx/lang-en-GB/mobile-0/appcentre-1/brand-4/xf-d43c9a446dde/candidate/so/pm/1/pl/2/opp/355-2027-Summer-Analyst-Investment-Banking-New-York-City/en-GB",
     "https://moelis-careers.tal.net/vx/lang-en-GB/mobile-0/appcentre-1/brand-4/xf-d43c9a446dde/candidate/so/pm/1/pl/2/opp/355-2027-Summer-Analyst-Investment-Banking-New-York-City/en-GB"),
    ("Moelis & Company — 2027 Summer Analyst, Investment Banking", "Houston, TX",
     "https://moelis-careers.tal.net/vx/mobile-0/appcentre-ext/brand-4/candidate/so/pm/1/pl/2/opp/348-2027-Summer-Analyst-Investment-Banking-Houston/en-GB",
     "https://moelis-careers.tal.net/vx/mobile-0/appcentre-ext/brand-4/candidate/so/pm/1/pl/2/opp/348-2027-Summer-Analyst-Investment-Banking-Houston/en-GB"),
    ("Moelis & Company — 2027 Summer Analyst, Investment Banking", "London, UK",
     "https://moelis-careers.tal.net/vx/lang-en-GB/mobile-0/appcentre-1/brand-4/user-7/xf-69860b0d6b25/wid-2/candidate/so/pm/1/pl/2/opp/391-2027-Summer-Analyst-Investment-Banking-London/en-GB",
     "https://moelis-careers.tal.net/vx/lang-en-GB/mobile-0/appcentre-1/brand-4/user-7/xf-69860b0d6b25/wid-2/candidate/so/pm/1/pl/2/opp/391-2027-Summer-Analyst-Investment-Banking-London/en-GB"),
    ("Principal Financial Group — Risk Management Internship 2027", "Des Moines, IA",
     "https://careers.principal.com/careers-home/jobs/52427?lang=en-us",
     "https://careers.principal.com/careers-home/jobs/52427?lang=en-us"),
    ("JPMorgan — 2027 Asset Management Product Summer Analyst Program", "New York, NY",
     "https://jpmc.fa.oraclecloud.com/hcmUI/CandidateExperience/en/sites/CX_1001/job/210691737",
     "https://jpmc.fa.oraclecloud.com/hcmUI/CandidateExperience/en/sites/CX_1001/job/210691737"),
    ("JPMorgan — 2027 Asset Management Client Summer Analyst Program", "New York, NY",
     "https://jpmc.fa.oraclecloud.com/hcmUI/CandidateExperience/en/sites/CX_1001/job/210691091",
     "https://jpmc.fa.oraclecloud.com/hcmUI/CandidateExperience/en/sites/CX_1001/job/210691091"),
    # Scotiabank — Global Banking and Markets, Equity Research Intern/Co-op,
    # Winter 2027 (Toronto): removed. It's a Winter term -- conflicts with
    # the user's spring semester, same reason "winter" is now excluded
    # everywhere else.
    # NOTE: Putnam (now part of Franklin Templeton) posts these on a Workday
    # site literally named "Invitation-Only" -- pages load fine but the actual
    # application may require a referral/invite code. Included so the user can
    # judge for themselves rather than being silently dropped.
    ("Putnam Investments (Franklin Templeton) — Equity Associate Intern", "Boston, MA",
     "https://franklintempleton.wd5.myworkdayjobs.com/en-US/Invitation-Only/job/Putnam-Equity-Associate-Intern_863131",
     "https://franklintempleton.wd5.myworkdayjobs.com/en-US/Invitation-Only/job/Putnam-Equity-Associate-Intern_863131"),
    # Bank of America: no public search API (custom platform, confirmed no
    # embedded JSON/API in the page source) -- but individual /students/
    # job-detail/ URLs are stable and checkable, so specific confirmed-live
    # postings are watchlisted directly. One other candidate ID (13932,
    # "Global Capital Markets Summer Analyst Program") 301-redirects to
    # /careers/errors/404.html -- confirmed dead, deliberately left out.
    ("Bank of America — Global Risk Summer Analyst Program 2027", "New York / Charlotte",
     "https://careers.bankofamerica.com/en-us/students/job-detail/14437/global-risk-summer-analyst-program-2027-multiple-locations",
     "https://careers.bankofamerica.com/en-us/students/job-detail/14437/global-risk-summer-analyst-program-2027-multiple-locations"),
    ("Bank of America — Global Markets (Sales & Trading) Summer Analyst 2027", "London, UK",
     "https://careers.bankofamerica.com/en-us/students/job-detail/14719/global-markets-sales-trading-private-side-rotational-programme-2027-summer-analyst-london-london-united-kingdom",
     "https://careers.bankofamerica.com/en-us/students/job-detail/14719/global-markets-sales-trading-private-side-rotational-programme-2027-summer-analyst-london-london-united-kingdom"),
    ("Bank of America — Global Investment Banking Summer Analyst 2027", "London, UK",
     "https://careers.bankofamerica.com/en-us/students/job-detail/14522/global-investment-banking-2027-summer-analyst-london-london-united-kingdom",
     "https://careers.bankofamerica.com/en-us/students/job-detail/14522/global-investment-banking-2027-summer-analyst-london-london-united-kingdom"),
    # Churchill Asset Management (TIAA/Nuveen affiliate): NOT added. Its
    # careers.tiaa.org URLs from search caches 404 on direct fetch, and its
    # tiaa.jobs mirror returns HTTP 200 for literally any path (client-side
    # routed SPA), so an HTTP check there proves nothing. No reliable way to
    # verify a specific posting yet -- still an open lead, not wired in.
]

INC = re.compile(r"\b(intern|internship|co-?op|apprentice)\b|"
                 # "summer analyst"/"summer associate" but many boards interject
                 # a year in between ("Summer 2027 Analyst") or reverse the
                 # order ("Analyst, Summer 2027") -- match either shape.
                 # ...and one optional word may sit between: Houlihan Lokey
                 # posts "Summer Financial Analyst", Baird "Summer Equity
                 # Analyst". INVEST + EXCLUDE still gate relevance, so this
                 # stays tight (Summer Marketing/HR/Technology Analyst all
                 # still fail).
                 r"summer\s*(?:20\d\d\s*)?(?:\w+\s+)?(?:analyst|associate)\b|"
                 r"(?:analyst|associate),?\s*summer\s*20\d\d\b", re.I)
# NOTE: no bare "analyst" here (RBC/BNY's non-investment tracks -- Procurement,
# QA, Investigation, generic corporate "Data/Business Analyst Intern" -- all
# have "analyst" in the title too, and INC's own "summer analyst" phrase
# already covers the case this was meant for). "invest(?!igat)" excludes
# "Investigation"/"Investigative", which otherwise match plain "invest".
INVEST = re.compile(r"(invest(?!igat)|equit|credit|private equity|growth equity|"
                    r"\bventure\b|portfolio|\bresearch\b|quant|capital markets|"
                    r"buyout|secondar|infrastructure|real estate|\brealty\b|fixed income|"
                    r"\bmacro\b|trading|\bdeal|diligence|asset manage|"
                    r"wealth manage|\bwealth\b|\brisk\b|\bfund\b|multi-?asset|\bpe\b|\bvc\b|"
                    r"commercial bank|corporate bank|global markets|transaction bank|"
                    r"m&a|merger|valuation|leveraged finance|restructuring|"
                    r"structured finance|underwrit|direct lending|senior lending|"
                    r"junior capital|unitranche|mezzanine|middle market|"
                    r"special situations|distressed|capital solutions|"
                    r"asset-based|\bsourcing\b|origination|manager research|"
                    r"investment strategy|investment analytics|\brating)", re.I)
# require the role to NOT be an old cycle / senior / grad-only; 2027 in the title optional
EXCLUDE = re.compile(r"(\bsenior\b|vice president|\bvp\b|\bdirector\b|principal|"
                     r"\bmanager\b|\blead\b|\bstaff\b|head of|\b202[0-6]\b|"
                     r"\bmba\b|ph\.?d|master('?s| or)|doctoral|full[- ]time|"
                     r"new grad|experienced|\btax\b|sales enablement|"
                     r"business development operations|(?<!campus )\brecruit|\bhr\b|"
                     r"human resources|\bmarketing\b|\blegal\b|\bcompliance\b|"
                     r"\baudit|\baccounting\b|payroll|facilities|help ?desk|"
                     r"total rewards|investor services|certified financial planner|"
                     r"financial planner|financial advisor|cybersecurity|"
                     r"software engineer|data engineer|network engineer|"
                     r"client support|help ?desk|\bcoop\b|co-?op|\bfraud\b|"
                     r"externship|communications|\bbrand\b|social media|"
                     # User's in school for spring semester -- off-cycle
                     # "Winter" co-op/intern terms (common at Canadian banks,
                     # usually 4-8 months) don't fit his calendar.
                     r"\bwinter\b|\bit internship\b|off[\s-]?cycle|year-?round|"
                     # explicit non-summer start dates ("January start",
                     # "Feb Start Date") -- same spring-semester conflict as
                     # Winter/off-cycle, just phrased without either word.
                     r"\((?:january|february|jan|feb)[^)]*start)", re.I)

# User: no restriction within the US (any state); outside the US, London,
# Paris, and Canada are fine too -- everywhere further afield is out.
ALLOWED_FOREIGN = re.compile(
    r"(london|united kingdom|\buk\b|england|\bparis\b|\bfrance\b|"
    r"\bcanada\b|toronto|montr[ée]al|vancouver|calgary|\bottawa\b|"
    r"\bontario\b|\bqu[ée]bec\b|british columbia|\balberta\b|"
    r",\s*on\b|,\s*qc\b|,\s*bc\b)", re.I)

FAR = re.compile(
    r"(singapore|hong ?kong|\bchina\b|shanghai|beijing|shenzhen|guangzhou|"
    r"\bjapan\b|tokyo|osaka|\bkorea\b|seoul|taiwan|taipei|\bindia\b|mumbai|"
    r"bengaluru|bangalore|new delhi|gurgaon|\buae\b|dubai|abu dhabi|riyadh|"
    r"\bqatar\b|doha|tel aviv|\bgermany\b|frankfurt|munich|berlin|"
    r"\bitaly\b|milan|\bspain\b|madrid|barcelona|netherlands|amsterdam|"
    r"\bbelgium\b|brussels|luxembourg|\bswitzerland\b|zurich|geneva|\bsweden\b|"
    r"\bireland\b|dublin|"
    r"stockholm|\bpoland\b|warsaw|\baustralia\b|sydney|melbourne|\bbrazil\b|"
    r"sao paulo|\bmexico\b|\bchile\b|bogota|\bperu\b|\bapac\b|\btaurus\b)",
    re.I)


def us_ok(loc: str) -> bool:
    if not loc:
        return True  # unknown location - could well be US, keep it
    if ALLOWED_FOREIGN.search(loc):
        return True
    return not FAR.search(loc)


def fetch(url, timeout=15):
    try:
        r = urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout)
        return r.status, r.read(1500000).decode("utf-8", "replace"), r.geturl()
    except urllib.error.HTTPError as e:
        return e.code, "", url
    except Exception as e:  # noqa: BLE001
        return None, f"{type(e).__name__}: {e}", url


def post_json(url, payload, timeout=20):
    try:
        req = urllib.request.Request(
            url, data=json.dumps(payload).encode(),
            headers={**UA, "Content-Type": "application/json", "Accept": "application/json"})
        r = urllib.request.urlopen(req, timeout=timeout)
        return r.status, r.read(400000).decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, ""
    except Exception:  # noqa: BLE001
        return None, ""


def from_workday(label, host, tenant, site, pure_investment_firm=False):
    """pure_investment_firm: the firm's whole business IS investing (e.g. Ares,
    a pure alternative-asset manager), so generic titles like "2027 Summer
    Intern" are relevant even without an investment keyword in the title."""
    seen_paths, out = set(), []
    for term in ("2027 summer analyst internship", "2027 intern investment",
                 "2027 credit analyst internship", "2027 intern", "summer intern 2027"):
        code, body = post_json(
            f"https://{host}/wday/cxs/{tenant}/{site}/jobs",
            {"searchText": term, "limit": 20, "offset": 0})
        if code != 200:
            continue
        try:
            posts = json.loads(body).get("jobPostings", [])
        except Exception:  # noqa: BLE001
            continue
        for p in posts:
            t = p.get("title", "")
            loc = p.get("locationsText", "")
            path = p.get("externalPath", "")
            if not path or path in seen_paths:
                continue
            # keep 2027 roles, or undated ones; drop anything tagged an older year
            year_ok = "2027" in t or not re.search(r"\b202[0-6]\b", t)
            ok = (INC.search(t) and not EXCLUDE.search(t) and not is_associate_only(t)) \
                if pure_investment_firm else want(t)
            if ok and us_ok(loc) and year_ok:
                seen_paths.add(path)
                # multi-brand tenants (e.g. "Prudential / PGIM") often post titles
                # that already lead with the sub-brand name ("PGIM: ...") -- drop
                # that so the digest doesn't read "Prudential / PGIM: PGIM: ...".
                disp_t = t
                m = re.match(r"^([A-Za-z][A-Za-z &]{2,30}):\s*(.+)$", t)
                if m and m.group(1).lower() in label.lower():
                    disp_t = m.group(2)
                # one extra fetch per already-qualifying job (small set) to
                # check its full description for an SIE mention -- Workday's
                # search results don't include description text.
                tag = ""
                dcode, dbody, _ = fetch(f"https://{host}/wday/cxs/{tenant}/{site}{path}")
                if dcode == 200:
                    try:
                        desc = json.loads(dbody).get("jobPostingInfo", {}).get("jobDescription", "")
                        tag = sie_tag(desc)
                    except Exception:  # noqa: BLE001
                        pass
                out.append((f"{label}: {disp_t}{tag}", loc, f"https://{host}/{site}{path}"))
    return out


def from_sig():
    """Susquehanna International Group runs its own custom careers API with a
    large internship program (quant research/trading, equity, macro, credit,
    ops...) across many locations. Their board API ignores offset/limit
    pagination for keyword search but one broad call returns the full list."""
    code, body, _ = fetch(
        "https://careers.sig.com/api/jobs?keywords=summer%202027%20intern&limit=100")
    if code != 200:
        return []
    try:
        jobs = json.loads(body).get("jobs", [])
    except Exception:  # noqa: BLE001
        return []
    out = []
    for j in jobs:
        d = j.get("data", {})
        t = d.get("title", "")
        loc = d.get("full_location", "")
        req_id = d.get("req_id")
        if not req_id or not want(t) or not us_ok(loc):
            continue
        out.append((f"Susquehanna (SIG): {t}", loc, f"https://careers.sig.com/job/{req_id}"))
    return out


# (label, cid, ccId) for firms whose careers site runs on ADP Workforce Now's
# public candidate portal, which exposes an unauthenticated JSON requisition
# feed at a fixed URL shape -- no keyword search needed, just list everything
# and filter client-side like from_sig().
ADP_WFN = [
    ("Valuation Research Corporation", "9b136ddc-361a-422a-b03c-668faab57287",
     "19000101_000001"),
]


ORACLE_HCM = [
    # (label, host, REST siteNumber, UI slug). BNY runs Oracle Cloud
    # Recruiting -- same family JPMorgan uses -- and its REST API returns
    # full requisition JSON with no auth. The REST siteNumber ("CX_1001")
    # and the candidate UI's friendly slug ("BNY-Careers", found via the
    # redirect a bare job/<id> URL 302s to) are different values.
    ("BNY", "eofe.fa.us2.oraclecloud.com", "CX_1001", "BNY-Careers"),
]


def from_oracle_hcm(label, host, site_number, ui_site):
    url = (f"https://{host}/hcmRestApi/resources/latest/recruitingCEJobRequisitions"
           "?onlyData=true&expand=requisitionList.secondaryLocations"
           f"&finder=findReqs;siteNumber={site_number},facetsList=LOCATIONS%3BWORK_LOCATIONS"
           "%3BTITLES%3BCATEGORIES%3BORGANIZATIONS%3BPOSTING_DATES%3BFLEX_FIELDS,limit=100,"
           "keyword=%222027%20summer%22")
    code, body, _ = fetch(url)
    if code != 200:
        return []
    try:
        reqs = json.loads(body)["items"][0].get("requisitionList", [])
    except Exception:  # noqa: BLE001
        return []
    out = []
    for r in reqs:
        t = r.get("Title", "")
        loc = r.get("PrimaryLocation", "")
        rid = r.get("Id")
        if not rid or not want(t) or not us_ok(loc):
            continue
        out.append((f"{label}: {t}", loc,
                    f"https://{host}/hcmUI/CandidateExperience/en/sites/{ui_site}/job/{rid}"))
    return out


def from_cacib():
    """Credit Agricole CIB runs on TalentSoft (ASP.NET WebForms, no JSON API),
    but unlike iCIMS/Schwab/MSCI it server-renders full job cards -- title,
    contract type, country, and city all sit in plain HTML -- so a page-by-page
    scrape works without a browser. Each job card looks like:
      <div class="ts-offer-card Layer" ...>
        <h3 class="ts-offer-card__title"><a href="...">TITLE</a></h3>
        ...
        <ul class="ts-offer-card-content__list">
          <li>Contract</li><li>Country</li><li>City</li>
        </ul>
      </div>
    """
    base = "https://jobs.ca-cib.com"
    out, seen_urls = [], set()
    for page in range(1, 6):
        code, body, _ = fetch(f"{base}/job/list-of-all-jobs.aspx?all=1&page={page}&LCID=2057")
        if code != 200:
            break
        cards = body.split('class="ts-offer-card Layer"')[1:]
        if not cards:
            break
        for c in cards:
            m = re.search(r'href="(/job/[^"]+\.aspx)"[^>]*title="[^"]*">\s*([^<]+?)\s*</a>', c)
            if not m:
                continue
            path, t = m.group(1), html.unescape(m.group(2)).strip()
            url = base + path
            if url in seen_urls:
                continue
            seen_urls.add(url)
            loc_m = re.search(r'<ul class="ts-offer-card-content__list[^"]*">(.*?)</ul>', c, re.S)
            loc = ""
            if loc_m:
                items = re.findall(r'<li[^>]*>([^<]+)</li>', loc_m.group(1))
                loc = ", ".join(html.unescape(x).strip() for x in items)
            if not want(t) or not us_ok(loc):
                continue
            out.append((f"Credit Agricole CIB: {t}", loc, url))
    return out


# (label, listing_url) for firms on tal.net (StepStone/Oleeo's older ATS --
# also server-renders full results, like TalentSoft). Deliberately left
# EMPTY: Jefferies' listing worked fine on first fetch but started serving
# an "oleeoProtect" JS challenge page (no real content) after a handful of
# requests in quick succession during testing -- confirmed by re-fetching
# the exact same URL with curl, which had worked minutes earlier. That's
# not safe to run unattended 8x/day: a source that can rate-limit itself
# mid-run risks silently going dark, or worse, getting flagged harder.
# from_tal_net() is kept for a manual one-off check, just not auto-run.
TAL_NET = []


def from_tal_net(label, listing_url):
    """Each result tile looks like:
      <div class="... candidate-opp-tile" data-title="TITLE">
        ...<a class="subject" href="APPLY_URL">TITLE</a>...
      </div>
    No separate location field -- the title itself always ends with the
    city ("... - New York"), so it doubles as both title and location text.
    Paginates via ?start=0,50,100...
    """
    out, seen_urls = [], set()
    for start in range(0, 300, 50):
        code, body, _ = fetch(f"{listing_url}?start={start}")
        if code != 200:
            break
        tiles = re.findall(r'data-title="([^"]+)">.*?href="([^"]+)"', body, re.S)
        if not tiles:
            break
        for title, url in tiles:
            t = html.unescape(title)
            if url in seen_urls:
                continue
            seen_urls.add(url)
            if not want(t) or not us_ok(t):
                continue
            out.append((f"{label}: {t}", t, url))
        if len(tiles) < 50:
            break
    return out


def from_adp_wfn(label, cid, ccid):
    url = ("https://workforcenow.adp.com/mascsr/default/careercenter/public/"
           f"events/staffing/v1/job-requisitions?cid={cid}&lang=en_US&clientId={ccid}&fromSF=Y")
    code, body, _ = fetch(url)
    if code != 200:
        return []
    try:
        reqs = json.loads(body).get("jobRequisitions", [])
    except Exception:  # noqa: BLE001
        return []
    out = []
    for r in reqs:
        t = r.get("requisitionTitle", "")
        item_id = r.get("itemID")
        locs = r.get("requisitionLocations", [])
        loc = locs[0].get("nameCode", {}).get("shortName", "") if locs else ""
        if not item_id or not want(t) or not us_ok(loc):
            continue
        apply_url = ("https://workforcenow.adp.com/mascsr/default/mdf/recruitment/"
                     f"recruitment.html?cid={cid}&ccId={ccid}&type=JS&lang=en_US&jobId={item_id}")
        out.append((f"{label}: {t}", loc, apply_url))
    return out


MASTERS = re.compile(r"(\bmba\b|ph\.?d|master('?s| or)|doctoral)", re.I)

# User: Summer 2027 only. A genuine summer program says "Summer" even when it
# also states a month count ("Summer 2027 Analyst (4 months)"); a generic
# undated rotational placement ("12-Month Internship", "6-month contract",
# common at European banks) never does. So only reject the month-duration
# pattern when "summer" is absent from the title.
NON_SUMMER_DURATION = re.compile(r"\b\d{1,2}[\s-]months?\b", re.I)

# Same idea, different phrasing: a rotational-track title can spell out its
# actual window ("January - June", "September - December") instead of using
# a month-count or the words winter/off-cycle. Any named non-summer month
# means the track doesn't run purely June-August -- reject unless "summer"
# is also in the title (covers "Summer 2027 (June - August)"-style ones).
NON_SUMMER_MONTH = re.compile(
    r"\b(january|february|march|april|september|october|november|december)\b", re.I)


def want(title: str) -> bool:
    if not (INC.search(title) and INVEST.search(title)):
        return False
    t = title
    # "(Undergraduate & Master's)" postings are open to undergrads — strip the
    # grad-degree wording before applying EXCLUDE so it doesn't drop them.
    if re.search(r"undergrad", t, re.I):
        t = MASTERS.sub("", t)
    if EXCLUDE.search(t):
        return False
    if not re.search(r"\bsummer\b", t, re.I) and NON_SUMMER_DURATION.search(t):
        return False
    if not re.search(r"\bsummer\b", t, re.I) and NON_SUMMER_MONTH.search(t):
        return False
    if is_associate_only(t):
        return False
    return True


def is_associate_only(t: str) -> bool:
    """User graduates May 2028, undergrad -- "Summer Associate" is the
    industry-standard MBA-track title (vs. "Summer Analyst" for undergrads).
    Only reject when the title is Associate-only; a combined "Analyst or
    Associate" posting still has an undergrad track and stays."""
    return bool(re.search(r"\bassociate\b", t, re.I) and not re.search(r"\banalyst\b", t, re.I))


def sie_tag(description_text: str) -> str:
    """User already passed the SIE (Securities Industry Essentials exam) --
    a real edge on postings that name it (usually broker-dealer sales/
    trading/wealth roles that require interns to sit for it). Flag it in
    the digest so these sort out for extra attention."""
    return SIE_TAG if re.search(r"\bSIE\b", description_text) else ""


def canon_role(role: str, loc: str) -> str:
    """Role title with the location stripped, so 'X Intern - Chicago, IL' and
    'X Intern - Atlanta, GA' collapse to the same group key across runs/days."""
    t = role
    frags = [f.strip() for f in re.split(r"[,/]", loc or "") if f.strip()]
    city = next((f for f in frags if len(f) > 2
                and f.upper() not in ("USA", "US", "UK")), None)
    if city:
        state = next((f for f in frags if re.fullmatch(r"[A-Z]{2}", f)), None)
        pat = re.escape(city) + (rf"(\s*,\s*{re.escape(state)})?" if state else "")
        t = re.sub(rf"[\s,\-–—(]*{pat}[\s,)]*", " ", t, flags=re.I)
    t = re.sub(r"\(\s*\)", "", t)
    if t.count("(") > t.count(")"):
        t = re.sub(r"\([^()]*$", "", t)  # drop an unmatched trailing "("
    t = re.sub(r"\s{2,}", " ", t).strip(" ,-–—")
    return t or role


def from_greenhouse(token):
    # content=true pulls the full HTML description in the same call (no
    # extra per-job fetch needed) so we can flag SIE mentions for free.
    code, body, _ = fetch(f"https://boards-api.greenhouse.io/v1/boards/{token}/jobs?content=true")
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
            out.append((t + sie_tag(j.get("content", "")), loc, j["absolute_url"]))
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
            desc = p.get("descriptionPlain", "") or p.get("description", "")
            out.append((t + sie_tag(desc), loc, p["hostedUrl"]))
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
    # urllib silently follows redirects -- a job page that now 301s to a
    # generic error page still reads back as HTTP 200 for the error page
    # itself. Catch that (seen live: a BofA job-detail URL redirecting to
    # /careers/errors/404.html) by checking where we actually landed.
    if re.search(r"/errors?/(404|not-?found)", final, re.I):
        return False
    low = body.lower()
    if any(m in low for m in ("no longer accepting", "position has been filled",
                              "this job is no longer", "job was removed",
                              "posting is not available", "error=true")):
        return False
    if re.search(r"[?&]error=true", final):
        return False
    # tal.net/Oleeo (Jefferies, Morgan Stanley) can serve a bot-check
    # challenge page instead of the real posting -- HTTP 200, no dead-marker
    # text, so it was silently read as "confirmed live" regardless of the
    # posting's actual status. Treat "can't verify" as not-live rather than
    # assume live.
    if "quick check needed" in low or "oleeoprotect" in low:
        return False
    return True


def main() -> int:
    # launchd's StandardOutPath log has no per-run markers otherwise, making
    # it impossible to tell from the log alone when (or whether) a run was
    # missed -- e.g. because the machine was asleep at the scheduled time.
    print(f"--- run start {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} ---")

    if not WEBHOOK and not DRY:
        print("no SLACK_WEBHOOK_URL", file=sys.stderr)
        return 2

    seen = {}
    if os.path.exists(SEEN_PATH):
        try:
            seen = json.load(open(SEEN_PATH))
        except Exception:  # noqa: BLE001
            seen = {}

    def nice(tok: str) -> str:
        if tok in NAMES:
            return NAMES[tok]
        return tok.replace("-", " ").replace("_", " ").title()

    found: list[tuple[str, str, str]] = []
    for tok in GREENHOUSE:
        found += [(f"{nice(tok)}: {t}", l, u) for t, l, u in from_greenhouse(tok)]
    for tok in LEVER:
        found += [(f"{nice(tok)}: {t}", l, u) for t, l, u in from_lever(tok)]
    for tok in ASHBY:
        found += [(f"{nice(tok)}: {t}", l, u) for t, l, u in from_ashby(tok)]
    for entry in WORKDAY:
        found += from_workday(*entry)
    found += from_sig()
    found += from_cacib()
    for label, url in TAL_NET:
        found += from_tal_net(label, url)
    for label, cid, ccid in ADP_WFN:
        found += from_adp_wfn(label, cid, ccid)
    for label, host, sn, ui in ORACLE_HCM:
        found += from_oracle_hcm(label, host, sn, ui)

    watch_ok, watch_dead = [], []
    for label, loc, chk, pub in WATCHLIST:
        (watch_ok if watch_live(chk) else watch_dead).append((label, loc, pub))

    # already applied — never re-surface (match on gh_jid / stable URL fragment)
    APPLIED = ("gh_jid=7895583", "gh_jid=7895562", "gh_jid=8041362",  # AQR SA roles
               "joinhandshake.com/public/jobs/11015271")               # StepStone PE Infra
    found = [(t, l, u) for (t, l, u) in found
             if not any(a in u for a in APPLIED)]

    new = [(t, l, u) for (t, l, u) in found if u not in seen]
    # keep watchlist live ones in seen too (so they aren't "new" every run)
    fresh_watch = [(lab, loc, pub) for lab, loc, pub in watch_ok if pub not in seen]

    if SIE_ONLY:
        # Watchlist entries aren't description-checked for SIE automatically,
        # but a few are manually confirmed and carry SIE_TAG in their label
        # already (see WATCHLIST) -- those still qualify here. Any watchlist
        # entry without the tag is left untouched (unseen) for the regular
        # run to pick up and post as usual.
        new = [r for r in new if SIE_TAG in r[0]]
        fresh_watch = [r for r in fresh_watch if SIE_TAG in r[0]]

    if not new and not fresh_watch:
        label = "SIE-mentioned roles" if SIE_ONLY else "new roles"
        print(f"no {label} ({len(found)} board hits, {len(watch_ok)} watchlist live).")
        return 0

    # bank / IB / AM / ER / PE summer-analyst roles first, everything else after
    new_sorted = sorted(new, key=lambda r: (not PRIORITY.search(r[0]), r[0].lower()))
    pri = [r for r in new_sorted if PRIORITY.search(r[0])]
    rest = [r for r in new_sorted if not PRIORITY.search(r[0])]

    def render_group(rows: list[tuple[str, str, str]]) -> list[str]:
        # Same firm posting the same role title in many cities (BMO Credit Analyst
        # Internship, DRW Quantitative Research Intern, etc.) reads as repeat spam
        # spread across days if each city gets its own line every time it's found.
        # Collapse them: one line per (firm, role-with-locations-stripped).
        groups: dict[tuple[str, str], list[tuple[str, str, str]]] = defaultdict(list)
        for t, l, u in rows:
            firm, _, role = t.partition(": ")
            groups[(firm, canon_role(role, l))].append((role, l, u))
        out = []
        for (firm, role_key), items in groups.items():
            if len(items) == 1:
                role, l, u = items[0]
                out.append(f"• {firm}: {role}{f' ({l})' if l else ''}\n  {u}")
                continue
            out.append(f"• {firm}: {role_key} — {len(items)} locations")
            for role, l, u in items[:6]:
                out.append(f"  {l or role}: {u}")
            if len(items) > 6:
                out.append(f"  …+{len(items) - 6} more (in seen_jobs.json)")
        return out

    header = (f":dart: {len(new)} live internship(s) mentioning the SIE exam — "
              f"links checked {TODAY}") if SIE_ONLY else (
             f":mag: {len(new) + len(fresh_watch)} new live internship(s) — "
             f"links checked {TODAY}")
    lines = [header]
    if pri:
        lines.append("\n*Bank / IB / AM / research / PE:*")
        lines += render_group(pri)
    for lab, loc, pub in fresh_watch:
        lines.append(f"• {lab}{f' ({loc})' if loc else ''}\n  {pub}")
    if rest:
        lines.append("\n*Other:*")
        lines += render_group(rest)
    text = "\n".join(lines)

    if DRY:
        print(text)
        return 0

    # Mark these seen ONLY after a confirmed successful post. A transient
    # failure here (classic case: DNS isn't back up yet right after the
    # machine wakes from sleep) must never silently swallow roles -- if we
    # marked them seen before posting and the post then failed, they'd be
    # gone for good (seen forever, delivered never). Retry a couple of
    # times for transient blips; if it still fails, leave everything unseen
    # so the next scheduled run picks these back up instead of losing them.
    posted = False
    last_err = None
    for attempt in range(3):
        try:
            urllib.request.urlopen(urllib.request.Request(
                WEBHOOK, data=json.dumps({"text": text}).encode(),
                headers={"Content-Type": "application/json"}), timeout=20).read()
            posted = True
            break
        except Exception as e:  # noqa: BLE001
            last_err = e
            if attempt < 2:
                time.sleep(5 * (attempt + 1))

    if not posted:
        print(f"ERROR: Slack post failed after 3 attempts, nothing marked seen: "
              f"{last_err}", file=sys.stderr)
        return 1

    for t, l, u in new:
        seen[u] = {"title": t, "first_seen": TODAY}
    for lab, loc, pub in fresh_watch:
        seen[pub] = {"title": lab, "first_seen": TODAY}
    json.dump(seen, open(SEEN_PATH, "w"), indent=2)

    label = "SIE-mentioned roles" if SIE_ONLY else "new roles"
    print(f"posted {len(new) + len(fresh_watch)} {label}.")
    return 0


class _Watchdog(Exception):
    pass


def _alarm_handler(signum, frame):  # noqa: ARG001
    raise _Watchdog("run exceeded the 15-minute hard limit")


if __name__ == "__main__":
    # Per-request timeouts (fetch()/post_json()) don't always cover every
    # hang mode -- seen twice in one day: a single request stalling for
    # over an hour despite its stated timeout (once on an RBC call, once on
    # a scheduled run that had to be killed by hand). A hard wall-clock
    # ceiling on the whole run means a future hang fails loud and fast
    # instead of silently blocking every scheduled run after it.
    signal.signal(signal.SIGALRM, _alarm_handler)
    signal.alarm(900)
    try:
        sys.exit(main())
    except _Watchdog as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)
