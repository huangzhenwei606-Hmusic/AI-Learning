# Studio Agent read-only connection

The independent Owner dashboard reads a bounded snapshot from
`GET /api/studio-agent/v1/snapshot?start=YYYY-MM-DD&end=YYYY-MM-DD`.

The endpoint is disabled (503) unless `HMUSIC_AGENT_READ_TOKEN` is set to at
least 32 random characters. Requests require `Authorization: Bearer <token>`;
Owner, parent, and teacher web sessions do not grant service access.

Configure the independent private Site with `CRM_BASE_URL` set to the actual
CRM HTTPS origin and `CRM_AGENT_TOKEN` set to that same dedicated token. Keep
both values in the respective hosting secret stores; never put tokens in Git,
URLs, browser code, or chat. GitHub contains code, not production schedule data.

The adapter uses the existing database backend. Reads use an explicit read-only
transaction and fixed table/column allowlists. It does not call schema setup,
send notifications, or modify schedules. Its request bypasses the CRM's lazy
schema/backup/reminder hook. Maintenance mode still applies.

The export excludes passwords, payment data, contact details and private notes.
Parent names from inquiry records are included for draft salutations. The date
range is at most 61 days; a per-table size limit fails explicitly instead of
silently truncating data. Missing optional schema produces warnings. Production
PostgreSQL connectivity and the complete data counts must be checked before
treating dashboard results as verified.

Run `python -m unittest test_studio_agent_connector` in an isolated test process.
Never point test runs or ad-hoc imports at the production database.
