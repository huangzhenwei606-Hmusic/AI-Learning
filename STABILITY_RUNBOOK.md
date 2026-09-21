# H-Music CRM Stability Runbook

## Reliability target

- `/healthz` responds within 1 second when the web process is alive.
- `/readyz` returns 200 only when the database can be read.
- Normal owner pages should complete server work in under 1.5 seconds.
- Calendar should remain usable while another request is slow.

## Protections in the application

1. Gunicorn uses four request threads so one slow page does not block the
   owner website, teacher app, and parent app together.
2. Requests time out after 60 seconds. The single worker is not recycled on a
   request counter because this disk-backed service has no standby worker.
3. SQLite uses WAL mode, a 15-second lock wait, and normal synchronization for
   better read/write concurrency on the Render persistent disk.
4. Schema preparation is serialized and cached once per process. Calendar no
   longer repeats table and index inspection every time it opens.
5. Requests slower than 1.5 seconds are logged with method, path, duration, and
   status. Every response also includes a `Server-Timing` header.
6. Render probes `/healthz`, which does not compete for a database lock.
   `/readyz` is available for database-aware monitoring.

## Monitoring

Configure an external monitor with two checks every five minutes:

- `https://hmusic-crm.onrender.com/healthz`
- `https://hmusic-crm.onrender.com/readyz`

Alert after two consecutive failures. In Render logs, search for
`Slow request` and investigate any path repeatedly above 1,500 ms.

## Deployment procedure

1. Run `python3 -m py_compile HMusic_CRM_Code_3eefd09/app.py`.
2. Run `python3 HMusic_CRM_Code_3eefd09/regression_checks.py`.
3. Push one focused commit.
4. Wait for `/healthz` and `/readyz` to return 200 three times.
5. Open Calendar twice. Treat the second load as the warm performance check.
6. Verify owner login, teacher login, parent login, and registration.
7. If checks fail, roll Render back to the previous successful commit.

## Remaining platform limitation

Render cannot provide true zero-downtime deploys for this service while it
uses a single SQLite database on a persistent disk. The durable next phase is
to migrate application data to managed PostgreSQL, run at least two web
instances, and move migrations into a release command. That removes the disk
handoff outage and allows rolling deploys. Until that migration is complete,
deploy during a quiet window and use the checks above before announcing the
site as available.
