# jobagent-early-warning

Persistent memory for a recurring cloud agent (Claude Code routine) whose job is
early discovery of Summer 2027 undergraduate growth-equity / investment
internships — before they close, the way Lead Edge Capital's and Radian
Capital's postings did.

This repo is intentionally separate from the main `jobagent` project (a local
cron pipeline that hits ATS JSON APIs directly). This one exists purely so a
stateless cloud session has something to read at the start of each run and
write back at the end, giving it memory across runs.

## Files

- `known_roles.yaml` — confirmed opportunities (same format/convention as the
  main jobagent project's file of the same name: `status: open|closed|check|applied`).
  The routine appends genuine discoveries here.
- `monitored_companies.txt` — companies already covered by the main jobagent
  project's automated ATS pipeline (resolved boards + tracked companies). The
  routine should not spend search budget rediscovering these; it should mainly
  hunt for firms NOT on this list, and for KelleyConnect / university-board
  postings regardless of company.
- `early_warning_state.json` — dedup ledger. Keyed by
  `normalized_company + normalized_role + location + summer_year`. Each entry
  tracks status (`NEW`, `ALREADY_REPORTED`, `APPLIED`, `CLOSED`,
  `DEADLINE_CHANGED`, `REOPENED`) plus discovery metadata (`date_first_discovered`,
  `recruitment_began`, `date_posted`, `application_deadline`, `date_last_verified`,
  `discovery_source`, `official_application_url`). The routine must read this
  before alerting and only surface genuinely new or changed entries.

## Posting policy — READ BEFORE SENDING ANYTHING TO SLACK

The routine's sandbox has **no network access** and CANNOT confirm a link is
live. The user still wants alerts, and wants a clickable link on every line.
So:

1. **Every candidate line in a Slack alert MUST carry a URL** — the most
   employer-direct link found (company ATS / Greenhouse / Lever / Workday /
   Ashby / iCIMS before any university-mirror or aggregator link). If no URL
   was found at all, write `(no link found — search only)` and list it last.
   A candidate name with no link is not acceptable.

2. **Never attach confidence language.** No "verified", "live", "durable",
   "confirmed", no fit scores, no "APPLY ASAP". Every routine alert is headed
   with a plain UNVERIFIED label saying the sandbox has no internet and nothing
   was checked. Overclaiming is what broke trust — links without claims are
   fine and wanted.

3. **Verification passes** (run from an interactive Claude Code session that
   *does* have network): pull everything logged since the last pass, fetch and
   check each URL for real, then post ONE consolidated message — live roles
   with their confirmed links, dead/closed ones listed by name only so they're
   not chased or re-surfaced. Update `early_warning_state.json` with the
   verified status + `official_application_url`.

Generated 2026-08-28. Posting policy added 2026-09-01.
