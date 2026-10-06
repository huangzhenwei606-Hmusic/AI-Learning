"""Offline tests: never use ambient DB/S3 configuration or construct an SDK client."""
import base64
import contextlib
import hashlib
import io
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import Mock, patch

import postgres_backup as module


SECRET = "synthetic-password-not-a-real-secret"
CONFIG = module.Config("postgresql://test:" + SECRET + "@localhost/synthetic", "test-bucket")


def fake_runner(args, **kwargs):
    if "--version" in args:
        return subprocess.CompletedProcess(args, 0, b"tool (PostgreSQL) 18.4\n", b"")
    if args[0] == "pg_dump":
        Path(args[-1]).write_bytes(b"PGDMPsynthetic-archive")
    return subprocess.CompletedProcess(args, 0, b"synthetic catalog", b"")


class FakeS3:
    def __init__(self):
        self.objects = {}
        self.calls = []

    def put_object(self, **kwargs):
        body = kwargs["Body"].read()
        assert len(body) == kwargs["ContentLength"]
        assert base64.b64encode(hashlib.sha256(body).digest()).decode() == kwargs["ChecksumSHA256"]
        self.objects[kwargs["Key"]] = (body, kwargs)
        self.calls.append(("put", kwargs["Key"]))

    def head_object(self, **kwargs):
        self.calls.append(("head", kwargs["Key"]))
        body, put = self.objects[kwargs["Key"]]
        return {"ContentLength": len(body), "ChecksumSHA256": put["ChecksumSHA256"],
                "Metadata": put["Metadata"], "VersionId": "synthetic-version"}


class BackupTests(unittest.TestCase):
    def test_success_integrity_order_cleanup_unique_keys(self):
        s3 = FakeS3()
        with tempfile.TemporaryDirectory() as root:
            first = module.backup(CONFIG, client=s3, runner=fake_runner, temp_root=root)
            second = module.backup(CONFIG, client=s3, runner=fake_runner, temp_root=root)
            self.assertEqual(list(Path(root).iterdir()), [])
        self.assertNotEqual(first["run_id"], second["run_id"])
        self.assertEqual([op for op, _ in s3.calls[:4]], ["put", "head", "put", "head"])
        self.assertTrue(s3.calls[2][1].endswith("/success.json"))
        body = s3.objects[s3.calls[2][1]][0]
        self.assertEqual(json.loads(body)["database"]["sha256"], first["database"]["sha256"])
        self.assertNotIn(SECRET, body.decode())
        self.assertNotIn("localhost", body.decode())
        self.assertTrue(first["started_at_utc"].endswith("+00:00"))

    def assert_failed_clean(self, runner=fake_runner, s3=None, code=None):
        s3 = s3 or FakeS3()
        with tempfile.TemporaryDirectory() as root:
            with self.assertRaises(module.BackupError) as caught:
                module.backup(CONFIG, client=s3, runner=runner, temp_root=root)
            self.assertEqual(list(Path(root).iterdir()), [])
        self.assertNotIn(SECRET, str(caught.exception))
        if code:
            self.assertEqual(str(caught.exception), code)
        return s3

    def test_dump_failure_no_cloud_calls_or_success(self):
        def fail(*args, **kwargs):
            raise subprocess.CalledProcessError(1, [SECRET], stderr=SECRET)
        s3 = self.assert_failed_clean(runner=fail, code="postgres_tool_failed")
        self.assertEqual(s3.calls, [])

    def test_timeout_redaction(self):
        def fail(*args, **kwargs):
            raise subprocess.TimeoutExpired(SECRET, 1)
        self.assert_failed_clean(runner=fail, code="postgres_tool_failed")

    def test_wrong_client_version(self):
        def old(args, **kwargs):
            return subprocess.CompletedProcess(args, 0, b"pg_dump (PostgreSQL) 17.1", b"")
        self.assert_failed_clean(runner=old, code="postgres_18_tools_required")

    def test_empty_and_invalid_dump(self):
        for data, code in [(b"", "dump_missing_or_empty"), (b"not-an-archive", "dump_format_invalid")]:
            def invalid(args, **kwargs):
                result = fake_runner(args, **kwargs)
                if args[0] == "pg_dump" and "--version" not in args:
                    Path(args[-1]).write_bytes(data)
                return result
            with self.subTest(code=code):
                self.assert_failed_clean(runner=invalid, code=code)

    def test_invalid_archive_catalog(self):
        def invalid(args, **kwargs):
            if args[0] == "pg_restore" and "--list" in args:
                raise RuntimeError(SECRET)
            return fake_runner(args, **kwargs)
        self.assert_failed_clean(runner=invalid, code="postgres_tool_failed")

    def test_dump_upload_failure_no_manifest(self):
        s3 = FakeS3()
        s3.put_object = lambda **kwargs: (_ for _ in ()).throw(RuntimeError(SECRET))
        self.assert_failed_clean(s3=s3, code="s3_put_failed:unknown")
        self.assertEqual(s3.objects, {})

    def test_safe_s3_diagnostics_never_emit_sdk_details(self):
        error = RuntimeError(SECRET)
        error.response = {"Error": {"Code": "AccessDenied", "Message": SECRET}, "secret": SECRET}
        self.assertEqual(module.safe_s3_failure(error, "put"), "s3_put_failed:AccessDenied")
        error.response["Error"]["Code"] = SECRET
        self.assertEqual(module.safe_s3_failure(error, "head"), "s3_head_failed:unknown")
        missing = type("NoCredentialsError", (Exception,), {})(SECRET)
        self.assertEqual(module.safe_s3_failure(missing, "put"), "s3_put_failed:credentials_missing")

    def test_integrity_mismatch_no_manifest(self):
        for field, value in [("ContentLength", -1), ("ChecksumSHA256", "wrong"), ("Metadata", {})]:
            s3 = FakeS3()
            original = s3.head_object
            def wrong(**kwargs):
                head = original(**kwargs)
                head[field] = value
                return head
            s3.head_object = wrong
            with self.subTest(field=field):
                self.assert_failed_clean(s3=s3, code="s3_integrity_mismatch")
                self.assertFalse(any(key.endswith("success.json") for key in s3.objects))

    def test_manifest_upload_failure_not_success(self):
        s3 = FakeS3()
        original = s3.put_object
        def fail(**kwargs):
            if kwargs["Key"].endswith("success.json"):
                raise RuntimeError(SECRET)
            return original(**kwargs)
        s3.put_object = fail
        self.assert_failed_clean(s3=s3, code="s3_put_failed:unknown")
        self.assertEqual(len(s3.objects), 1)  # preserve orphan dump, no delete needed

    def test_head_failure_no_manifest(self):
        s3 = FakeS3()
        s3.head_object = lambda **kwargs: (_ for _ in ()).throw(RuntimeError(SECRET))
        self.assert_failed_clean(s3=s3, code="s3_head_failed:unknown")
        self.assertFalse(any(key.endswith("success.json") for key in s3.objects))

    def test_manifest_verification_failure_cli_nonzero(self):
        s3 = FakeS3()
        original = s3.head_object
        def fail(**kwargs):
            if kwargs["Key"].endswith("success.json"):
                raise RuntimeError(SECRET)
            return original(**kwargs)
        s3.head_object = fail
        actual_backup = module.backup
        output = io.StringIO()
        with patch.object(module.Config, "from_env", return_value=CONFIG), \
             patch.object(module, "backup", side_effect=lambda config: actual_backup(config, client=s3, runner=fake_runner)), \
             contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
            self.assertEqual(module.main(), 1)
        self.assertNotIn("backup verified", output.getvalue())
        self.assertNotIn(SECRET, output.getvalue())

    def test_large_dump_rejected_without_upload(self):
        path = Mock()
        path.stat.return_value.st_size = 5 * 1024 ** 3
        s3 = FakeS3()
        with self.assertRaisesRegex(module.BackupError, "single_put_size_limit"):
            module.put_verified(s3, "test", "test", path, "application/octet-stream")
        self.assertEqual(s3.calls, [])

    def test_head_checksum_missing_fails_closed(self):
        s3 = FakeS3()
        original = s3.head_object
        def missing(**kwargs):
            head = original(**kwargs)
            head.pop("ChecksumSHA256")
            return head
        s3.head_object = missing
        self.assert_failed_clean(s3=s3, code="s3_integrity_mismatch")
        self.assertFalse(any(key.endswith("success.json") for key in s3.objects))

    def test_credentials_never_in_command_and_uri_options_preserved(self):
        calls = []
        def observe(args, **kwargs):
            calls.append((args, kwargs["env"]))
            return fake_runner(args, **kwargs)
        module.backup(CONFIG, client=FakeS3(), runner=observe)
        self.assertNotIn(SECRET, repr([args for args, _ in calls]))
        self.assertEqual(calls[0][1]["PGPASSWORD"], SECRET)
        env = module.connection_env("postgresql://u:p%40ss@localhost/d?sslmode=require")
        self.assertEqual(env["PGPASSWORD"], "p@ss")
        self.assertEqual(env["PGSSLMODE"], "require")
        self.assertNotIn(SECRET, repr(CONFIG))

    def test_bad_configuration(self):
        for env in ({}, {"DATABASE_URL": CONFIG.database_url},
                    {"DATABASE_URL": CONFIG.database_url, "HMUSIC_BACKUP_S3_BUCKET": "b",
                     "HMUSIC_POSTGRES_BACKUP_TIMEOUT_SECONDS": "0"}):
            with self.assertRaises(module.BackupError):
                module.Config.from_env(env)
        for url in ("sqlite:///test", "postgresql://u:p@pgbouncer/d", "postgresql://u:p@localhost/d?options=secret"):
            with self.assertRaises(module.BackupError):
                module.connection_env(url)

    def test_cli_redacts_unexpected_exception(self):
        stderr = io.StringIO()
        stdout = io.StringIO()
        with patch.object(module.Config, "from_env", return_value=CONFIG), \
             patch.object(module, "backup", side_effect=RuntimeError(SECRET)), \
             contextlib.redirect_stderr(stderr), contextlib.redirect_stdout(stdout):
            self.assertEqual(module.main(), 1)
        self.assertEqual(stdout.getvalue(), "")
        self.assertNotIn(SECRET, stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
