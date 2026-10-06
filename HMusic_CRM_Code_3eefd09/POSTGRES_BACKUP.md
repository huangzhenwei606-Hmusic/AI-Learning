# PostgreSQL logical backups to the existing S3 bucket

This command supplements Render PITR. It is not deployed, scheduled, or connected
to production by this change. It does not enable the legacy SQLite backup hook.
It backs up one database's schema/data, not cluster roles/tablespaces or S3
attachments. A database snapshot and independently changing S3 objects are not
an atomic combined backup. Preserve attachment versions separately.

## Required checks before deployment

1. Privately verify the production app's direct database host matches the intended
   Render database. The existing UI only proves PostgreSQL is active. Never send
   a connection URL/password to chat or place one in documentation or logs.
2. Verify a direct connection, not PgBouncer/another transaction pooler. The command
   rejects obvious `pgbouncer` hostnames but cannot detect all poolers. Use the
   database's direct internal address from a job in the same Render region/network.
3. Build and validate `Dockerfile.postgres-backup`, which packages PostgreSQL
   **18** clients, Python and the dedicated boto3 dependency. A Python dependency
   on psycopg does not install these binaries. No image deployment is applied here.
4. Verify the destination is the existing HMusic account bucket
   `hmusic-crm-backups-xu`, region `us-east-1`. Do not create a Xutrading bucket.
   The existing optional custom endpoint is supported only if it implements
   SHA-256 PUT and HEAD checksum verification. Missing checksums fail closed.
5. Confirm existing credentials permit `PutObject` and checksum-enabled `HeadObject`
   (`GetObject`) for the chosen prefix. A KMS configuration can require additional
   permissions. Do not grant broad S3 access or create keys automatically.

## Configuration and execution

Run `python run_postgres_backup.py` from this directory in an explicitly authorized
job. Importing the module does nothing and importing Flask/app.py is unnecessary.
Provide existing credentials through the hosting platform's secure configuration;
the command uses boto3's standard credential provider chain without printing them.

### Dedicated cron container

Build from this directory with:

```sh
docker build -f Dockerfile.postgres-backup -t hmusic-postgres-backup .
docker run --rm --entrypoint sh hmusic-postgres-backup -c 'python --version; pg_dump --version; pg_restore --version'
```

The Dockerfile uses the official `postgres:18-bookworm` image, installs Python in
a virtual environment, and overrides the image entrypoint so it never starts a
database server. It runs as the non-root `postgres` OS user. Docker's matching
`Dockerfile.postgres-backup.dockerignore` excludes all context files except the
five necessary build/runtime files; no `.env`, application data, or other source
is sent in the build context. Pin an image digest after the actual image is built
and verified; the major-version tag itself can receive upstream patches.

For an independently approved Render Docker cron, set the root directory to
`HMusic_CRM_Code_3eefd09`, Dockerfile path to `Dockerfile.postgres-backup`, and
Docker context to this directory (paths are relative to the configured root).
Keep Docker Command empty so the image entrypoint runs the supervisor. Do not
use the native Python draft's build command or bypass the supervisor by overriding
the image entrypoint. Verify the resolved paths in Render before submission.

`run_postgres_backup.py` imposes a fixed 3,600-second wall-clock deadline on the
entire child process group, including dumping, catalog validation, hashing,
SDK retries and uploads. It sends TERM at the deadline, escalates to KILL within
10 seconds, and returns 124 with a fixed redacted timeout message. It preserves
normal child exit codes. This bound is independent of environment configuration.
Termination may leave a dump or an ambiguously committed manifest in S3; use job
exit status and verification together. Ephemeral local files disappear with the
container. Scheduling/platform startup and shutdown overhead is outside this bound.

### Proposed access policy — requires separate approval; never applied by code

Copying or referencing the app's database URL preserves the app role's permissions;
it does not create read-only access. For a dedicated login, an administrator should
first verify the exact production database, schemas, object owners and RLS use,
then securely create a password outside chat. The target grants are:

```sql
-- Templates only; replace identifiers after privately verifying the database.
-- CREATE ROLE hmusic_backup LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE
--   NOREPLICATION NOBYPASSRLS; set its password through a secure admin prompt.
GRANT CONNECT ON DATABASE target_database TO hmusic_backup;
GRANT USAGE ON SCHEMA target_schema TO hmusic_backup;
GRANT SELECT ON ALL TABLES IN SCHEMA target_schema TO hmusic_backup;
GRANT SELECT ON ALL SEQUENCES IN SCHEMA target_schema TO hmusic_backup;
ALTER DEFAULT PRIVILEGES FOR ROLE object_owner IN SCHEMA target_schema
    GRANT SELECT ON TABLES TO hmusic_backup;
ALTER DEFAULT PRIVILEGES FOR ROLE object_owner IN SCHEMA target_schema
    GRANT SELECT ON SEQUENCES TO hmusic_backup;
```

Repeat schema and default grants for every intended schema and each actual object
creator; default privileges are not retroactive. Do not grant sequence USAGE
(which permits `nextval`), ownership, write roles, or server-file/program access.
Audit role membership and effective PUBLIC grants (including schema CREATE,
database TEMP, and write-capable function EXECUTE). Per-role grants cannot negate
PUBLIC privileges: removing shared privileges can affect the app and needs its
own review. A read-only transaction default is defense in depth, not permission
enforcement. Large objects need separate SELECT grants if present. RLS causes
the full dump to fail unless the role can read all required rows; do not silently
enable partial row-security dumps or grant BYPASSRLS without specific approval.
Do not use cluster-wide `pg_read_all_data` as an unexplained shortcut.

For the existing SSE-S3 bucket, the job's dedicated AWS identity needs only:

```json
{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Action": ["s3:PutObject", "s3:GetObject"],
    "Resource": "arn:aws:s3:::hmusic-crm-backups-xu/hmusic-crm/postgresql/*"
  }]
}
```

Verify that no additional identity, group or resource policies broaden access.
No ListBucket, ACL, deletion, bucket management, old SQLite/attachment prefix,
or GetObjectVersion grant is required by this job. HeadObject uses GetObject,
which also allows object downloads; do not describe it as metadata-only access.
PutObject allows overwriting a key: unique UUID keys reduce accidents but this
policy does not enforce append-only storage or immutability. A stronger policy
would require separately approved conditional writes/Object Lock and matching
code, not a claim that versioning prevents overwrite.

Render Blueprint `fromService`/`envVarKey` references preserve existing credential
permissions. `fromDatabase`/`connectionString` references the default DB user,
not a dedicated SQL-created role. Render's New default credential changes the
default user, so avoid it for this backup login. A dedicated SQL-created login
URL should be entered by the human into `HMUSIC_BACKUP_DIRECT_DATABASE_URL` via
secure Render configuration, never copied into chat or logs. Dedicated AWS key
entry likewise requires human handoff. If the workspace already supports Render
AWS OIDC (Pro or higher), a service-specific trust policy and the prefix policy
can use temporary credentials via AWS_ROLE_ARN; do not upgrade the plan or create
provider/role/trust configuration without exact authorization.

| Variable | Purpose |
| --- | --- |
| `HMUSIC_BACKUP_DIRECT_DATABASE_URL` | Optional direct PostgreSQL URI override; securely supplied |
| `DATABASE_URL` | Existing connection used if the direct override is absent |
| `HMUSIC_BACKUP_S3_BUCKET` | Required existing bucket |
| `HMUSIC_BACKUP_S3_PREFIX` | Existing prefix; defaults to `hmusic-crm` |
| `AWS_DEFAULT_REGION` / `AWS_REGION` | Existing region; defaults to `us-east-1` |
| `HMUSIC_BACKUP_S3_ENDPOINT_URL` | Optional existing S3-compatible endpoint |
| `HMUSIC_POSTGRES_BACKUP_TIMEOUT_SECONDS` | Per dump/catalog command timeout; default 1800 |

Only PostgreSQL URIs with an explicit database/user are accepted. Supported URI
query options: `sslmode`, `sslrootcert`, `sslcert`, `sslkey`, `connect_timeout`.
Other options fail rather than being silently dropped. Connection credentials
go to libpq environment variables, never command arguments. Use the platform's
TLS requirements; do not change network/TLS permissions to make the job work.

Objects use `<prefix>/postgresql/<UTC timestamp>_<random UUID>/database.dump`
and `success.json`. Keys are unique across concurrent/repeated runs. The manifest
records timestamps, format, size, SHA-256, and returned object version ID; it
contains no host, database name, password, students, or connection URL.

The job validates custom-format magic and `pg_restore --list`, uploads using an
explicit SHA-256 checksum, and verifies S3 HEAD length/checksum/metadata before
publishing a success manifest. It verifies the manifest upload too. It returns
nonzero with fixed redacted error codes on failure. Temporary files are removed
on normal success/failure; host termination may prevent cleanup, so use ephemeral
job storage. Dump/catalog validation is not proof of restoreability.

Single PUT supports dumps **smaller than 5 GiB**. Larger files fail before upload;
multipart/full-object-checksum support requires a separate change. SDK retries
are handled by boto3 defaults. Failed uploads can leave orphan dumps or, after an
ambiguous manifest request, a manifest. The job never deletes cloud objects.
Treat process exit status, validated manifest, and object/version checksum together
as evidence; do not mark a failed job successful solely from a file name.

## Scheduling and retention

First inspect whether an existing scheduler can call this command. No fixed cron
is defined by this patch. If a new Render cron is approved, proposed initial
schedule: daily at **03:00 UTC** (`0 3 * * *`), in the database's Oregon region.
Securely configure the job separately; web-service environment variables do not
automatically carry over. The UTC hour is a proposal, not an applied setting.
Do not run dumps in a Flask before-request hook or enable old SQLite automation.

No `render.yaml` changes are included: the old blueprint declares a persistent
disk that differs from the observed production service. Applying it could change
unrelated infrastructure. A dedicated job can be deployed without redeploying the
web app once configuration and cost are approved.

No retention/deletion is applied. Existing S3 versioning is preserved. A later
approved retention policy should scope both current and noncurrent versions to
the PostgreSQL subprefix only, retaining historical SQLite objects and attachments.
Storage continues growing until retention is deliberately configured.

At the observed $0.00016/min compute price, daily runs bounded to 60 minutes plus
10 seconds are approximately $0.30/month before the $1/month cron minimum and
platform overhead. Extra/manual runs add cost. This bounds active script runtime,
not total spend: S3 current/noncurrent versions and orphan dumps accumulate,
Render outbound traffic and restore costs remain unmeasured. The 5 GiB per-dump
limit does not enforce a $20 monthly cap. Measure actual dump size and egress and
agree retention before describing the arrangement as within a lasting budget.

Costs: job runtime/minimum service charge, Render outbound transfer to us-east-1,
S3 dump and version storage, PUT/HEAD requests, and isolated restore compute/storage.
Database size, compression, duration, other account charges, and incremental totals
remain unknown. AWS credits do not cover Render charges. No cloud services or
spending are authorized by this code change.

## Verification and isolated restore

Offline unit tests: `python -m unittest -v test_postgres_backup.py test_run_postgres_backup.py`.
Explicit synthetic local PostgreSQL 18 test (requires preinstalled tools only):
`python check_postgres_backup_roundtrip.py`. This creates a temporary localhost
cluster with synthetic data and fake S3, then stops/removes it. Neither test uses
ambient application connection strings or constructs a real S3 client.

After separate approval for production backup/restore testing:

1. Run one job and verify a zero exit status, manifest, timestamps, returned
   version ID, size, and SHA-256. Failures must alert an operator; no notification
   destination is configured by this patch.
2. Retrieve the exact version recorded in the manifest into an authorized secure
   restore environment; verify its SHA-256 before use.
3. Restore with PostgreSQL 18 `pg_restore --exit-on-error --no-owner` into a separate
   **empty** test database, using its securely supplied connection configuration.
   Never target production or run `--clean` there.
4. Check expected tables, constraints, sequences, representative aggregate counts,
   and application read behavior. Validate attachment references/version availability
   separately. Avoid logging student rows. Record the tested backup version/date.
5. Delete test resources/data only with authorization and the agreed retention policy.

Until a production export and isolated restore are verified, report the system as
"backup code prepared", not "production backup fixed".
