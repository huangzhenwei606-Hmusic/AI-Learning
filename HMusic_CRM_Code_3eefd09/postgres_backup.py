"""Standalone logical backup; importing this module performs no I/O.

Run only in an explicitly configured backup job, never a Flask request hook.
"""
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from urllib.parse import unquote, urlsplit, parse_qs
from uuid import uuid4


class BackupError(Exception):
    """Safe, fixed diagnostic codes only; never include SDK/subprocess errors."""


@dataclass(frozen=True, repr=False)
class Config:
    database_url: str
    bucket: str
    prefix: str = "hmusic-crm"
    region: str = "us-east-1"
    endpoint_url: str | None = None
    timeout_seconds: int = 1800

    @classmethod
    def from_env(cls, env):
        url = env.get("HMUSIC_BACKUP_DIRECT_DATABASE_URL") or env.get("DATABASE_URL", "")
        bucket = env.get("HMUSIC_BACKUP_S3_BUCKET", "").strip()
        if not url or not bucket:
            raise BackupError("configuration_missing")
        try:
            timeout = int(env.get("HMUSIC_POSTGRES_BACKUP_TIMEOUT_SECONDS", "1800"))
        except ValueError:
            raise BackupError("configuration_invalid") from None
        if timeout <= 0:
            raise BackupError("configuration_invalid")
        return cls(url, bucket, env.get("HMUSIC_BACKUP_S3_PREFIX", "hmusic-crm").strip("/"),
                   env.get("AWS_DEFAULT_REGION") or env.get("AWS_REGION") or "us-east-1",
                   env.get("HMUSIC_BACKUP_S3_ENDPOINT_URL") or None, timeout)


def connection_env(url):
    """Convert a direct URI to libpq env, keeping credentials out of argv/logs."""
    try:
        parsed = urlsplit(url)
        if parsed.scheme not in ("postgres", "postgresql") or not parsed.hostname or parsed.fragment:
            raise ValueError()
        if "pgbouncer" in parsed.hostname.lower():
            raise ValueError()
        database = unquote(parsed.path.lstrip("/"))
        if not database or not parsed.username:
            raise ValueError()
        query = parse_qs(parsed.query, keep_blank_values=True)
        # Do not silently drop session-affecting URI options.
        allowed = {"sslmode", "sslrootcert", "sslcert", "sslkey", "connect_timeout"}
        if set(query) - allowed or any(len(v) != 1 for v in query.values()):
            raise ValueError()
        env = {k: v for k, v in os.environ.items()
               if not k.startswith("PG") and k not in ("DATABASE_URL", "HMUSIC_BACKUP_DIRECT_DATABASE_URL")}
        env.update(PGHOST=parsed.hostname, PGPORT=str(parsed.port or 5432),
                   PGDATABASE=database, PGUSER=unquote(parsed.username),
                   PGPASSWORD=unquote(parsed.password or ""), PGCONNECT_TIMEOUT="15")
        names = {"sslmode": "PGSSLMODE", "sslrootcert": "PGSSLROOTCERT", "sslcert": "PGSSLCERT",
                 "sslkey": "PGSSLKEY", "connect_timeout": "PGCONNECT_TIMEOUT"}
        for key, values in query.items():
            env[names[key]] = values[0]
        return env
    except (ValueError, TypeError):
        raise BackupError("direct_database_uri_invalid") from None


def run_tool(args, env, timeout, runner=subprocess.run):
    try:
        return runner(args, env=env, check=True, stdout=subprocess.PIPE,
                      stderr=subprocess.PIPE, timeout=timeout)
    except Exception:
        # libpq/SDK messages can contain URLs, passwords, and student identifiers.
        raise BackupError("postgres_tool_failed") from None


def create_dump(config, path, runner=subprocess.run):
    env = connection_env(config.database_url)
    for tool in ("pg_dump", "pg_restore"):
        result = run_tool([tool, "--version"], env, 15, runner)
        if not re.search(rb"PostgreSQL\) 18(?:\.|\s)", result.stdout):
            raise BackupError("postgres_18_tools_required")
    run_tool(["pg_dump", "--format=custom", "--no-password", "--file", str(path)],
             env, config.timeout_seconds, runner)
    if not path.is_file() or path.stat().st_size == 0:
        raise BackupError("dump_missing_or_empty")
    with path.open("rb") as source:
        if source.read(5) != b"PGDMP":
            raise BackupError("dump_format_invalid")
    # Validate archive catalog locally, without connecting to a database.
    run_tool(["pg_restore", "--list", str(path)], env, config.timeout_seconds, runner)


def digest_file(path):
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest(), base64.b64encode(digest.digest()).decode("ascii")


def put_verified(client, bucket, key, path, content_type):
    size = path.stat().st_size
    # Single PUT keeps checksum verification unambiguous; multipart needs a
    # separate implementation with full-object checksum validation.
    if size >= 5 * 1024 ** 3:
        raise BackupError("single_put_size_limit")
    sha256, checksum = digest_file(path)
    try:
        with path.open("rb") as source:
            client.put_object(Bucket=bucket, Key=key, Body=source,
                              ContentLength=size, ContentType=content_type,
                              ChecksumSHA256=checksum, Metadata={"sha256": sha256})
        head = client.head_object(Bucket=bucket, Key=key, ChecksumMode="ENABLED")
    except Exception:
        raise BackupError("s3_upload_or_verification_failed") from None
    if (head.get("ContentLength") != size or head.get("ChecksumSHA256") != checksum
            or head.get("Metadata", {}).get("sha256") != sha256):
        raise BackupError("s3_integrity_mismatch")
    return {"key": key, "bytes": size, "sha256": sha256,
            "version_id": head.get("VersionId")}


def make_client(config):
    try:
        import boto3
        return boto3.client("s3", region_name=config.region, endpoint_url=config.endpoint_url)
    except Exception:
        raise BackupError("s3_client_unavailable") from None


def backup(config, *, client=None, runner=subprocess.run, temp_root=None):
    """Return success only after dump and manifest both pass S3 verification.

    On a later failure, uploaded objects are deliberately left intact; no delete
    privileges are needed. An absent success manifest identifies an incomplete run.
    """
    started = datetime.now(timezone.utc).isoformat()
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "_" + uuid4().hex
    prefix = "/".join(p for p in (config.prefix.strip("/"), "postgresql", run_id) if p)
    with tempfile.TemporaryDirectory(prefix="hmusic-pg-backup-", dir=temp_root) as folder:
        dump = Path(folder) / "database.dump"
        create_dump(config, dump, runner)
        if client is None:
            client = make_client(config)
        uploaded = put_verified(client, config.bucket, prefix + "/database.dump", dump,
                                "application/octet-stream")
        manifest = {"schema_version": 1, "status": "success", "run_id": run_id,
                    "started_at_utc": started,
                    "dump_verified_at_utc": datetime.now(timezone.utc).isoformat(),
                    "format": "pg_dump_custom", "client_major_version": 18,
                    "scope": "one_database_schema_and_data; excludes_cluster_globals_and_s3_attachments",
                    "database": uploaded}
        manifest_path = Path(folder) / "success.json"
        manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        put_verified(client, config.bucket, prefix + "/success.json", manifest_path,
                     "application/json")
        return manifest


def main():
    try:
        manifest = backup(Config.from_env(os.environ))
    except BackupError as error:
        print("PostgreSQL backup failed: " + str(error), file=sys.stderr)
        return 1
    except Exception:
        print("PostgreSQL backup failed: unexpected_failure", file=sys.stderr)
        return 1
    print("PostgreSQL backup verified: " + manifest["run_id"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
