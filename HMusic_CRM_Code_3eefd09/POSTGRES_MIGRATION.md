# PostgreSQL migration runbook

The production service remains on SQLite until every rehearsal gate below has
passed. Never remove the persistent disk before the rollback window ends.

## Phase 1: Compatibility

- Keep `DATABASE_URL` unset in production.
- Run `database_backend_checks.py` and `regression_checks.py` during every build.
- Rehearse against a disposable PostgreSQL database using a copy of SQLite.
- Verify owner, teacher, parent, registration, calendar, billing, messages, and
  course-credit workflows.

## Phase 2: Render rehearsal database

1. Create a paid Render PostgreSQL database in the same region as the web service.
2. Enable point-in-time recovery and storage autoscaling where the selected plan supports them.
3. Use the external URL only for the controlled import. Use the internal URL for the web service.
4. Export a fresh SQLite backup from the persistent disk.
5. Import it into the rehearsal database:

   ```bash
   python migrate_sqlite_to_postgres.py \
     --sqlite /path/to/hmusic.db \
     --database-url "$REHEARSAL_DATABASE_URL" \
     --replace
   ```

6. Save the per-table verification report and resolve every mismatch.

## Phase 3: Production cutover

1. Announce a short write freeze. Reads may stay available.
2. Create and checksum a final SQLite backup.
3. Run the final import and row-count verification.
4. Add the internal PostgreSQL URL as `DATABASE_URL`.
5. Deploy one web instance and run smoke tests.
6. Remove the web service disk only after the PostgreSQL deployment is verified.
7. Scale the stateless web service to two instances.
8. Verify `/healthz`, `/readyz`, response times, and all critical workflows.

## Rollback

- Keep the final SQLite backup and disk unchanged for 14 days.
- During the initial cutover window, rollback means removing `DATABASE_URL` and
  redeploying the last SQLite-compatible release.
- After PostgreSQL accepts new production writes, never silently switch back to
  the stale SQLite file. Export the PostgreSQL delta or schedule a controlled rollback.

## Acceptance gates

- Every table count matches.
- Critical entity samples match by ID and business key.
- Owner, teacher, and parent authentication pass.
- Calendar month view and schedule writes pass.
- Registration, invoices, payments, credits, messages, and reminders pass.
- Two web instances remain healthy during a rolling deploy.
