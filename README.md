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

Generated 2026-08-28.
