from __future__ import annotations

import argparse
import contextlib
import importlib.machinery
import importlib.util
import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]


def load_bootstrap_module() -> Any:
    path = ROOT / "bootstrap-immich-api-key"
    loader = importlib.machinery.SourceFileLoader(
        "media_inbox_bootstrap_test", str(path)
    )
    spec = importlib.util.spec_from_loader(loader.name, loader)
    if spec is None:
        raise RuntimeError("could not load bootstrap helper")
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


class HelperTests(unittest.TestCase):
    def test_bootstrap_creates_exact_permissions_without_printing_secrets(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            temp = Path(temporary)
            output = temp / "immich_api_key"
            metadata = temp / "immich_api_key.json"
            source_value = "source-bootstrap-test-value"
            created_value = "new-scoped-test-value"
            created_body: dict[str, Any] = {}
            module = load_bootstrap_module()
            module.parse_args = lambda: argparse.Namespace(
                api_url="http://immich/api",
                source_container="helper",
                source_env="API_KEY",
                name="immich-media-inbox",
                output=output,
                metadata_output=metadata,
                require_new_backup=True,
                backup_timeout=60,
            )
            module.source_key_from_container = lambda container, name: source_value

            def fake_api_request(
                api_url: str,
                key: str,
                method: str,
                path: str,
                body: dict[str, Any] | None = None,
            ) -> Any:
                del api_url
                if method == "GET" and path == "/admin/database-backups":
                    calls = getattr(fake_api_request, "backup_calls", 0)
                    fake_api_request.backup_calls = calls + 1
                    if calls == 0:
                        return {"backups": [{"filename": "old.sql.gz", "filesize": 50}]}
                    return {
                        "backups": [
                            {"filename": "old.sql.gz", "filesize": 50},
                            {
                                "filename": "new.sql.gz",
                                "filesize": 100,
                                "timezone": "America/Chicago",
                            },
                        ]
                    }
                if method == "POST" and path == "/jobs":
                    self.assertEqual(body, {"name": "backup-database"})
                    return None
                if method == "GET" and path == "/api-keys":
                    self.assertEqual(key, source_value)
                    return []
                if method == "POST" and path == "/api-keys":
                    self.assertEqual(key, source_value)
                    created_body.update(body or {})
                    return {
                        "apiKey": {
                            "id": "12345678-1234-1234-1234-123456789abc",
                            "name": "immich-media-inbox",
                            "createdAt": "2026-08-09T12:00:00Z",
                        },
                        "secret": created_value,
                    }
                if method == "GET" and path == "/api-keys/me":
                    self.assertEqual(key, created_value)
                    return {"permissions": ["asset.read"]}
                self.fail(f"unexpected API request: {method} {path}")

            module.api_request = fake_api_request
            module.time.sleep = lambda seconds: None
            stdout = io.StringIO()
            stderr = io.StringIO()
            with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                self.assertEqual(module.main(), 0)
            combined = stdout.getvalue() + stderr.getvalue()
            self.assertNotIn(source_value, combined)
            self.assertNotIn(created_value, combined)
            self.assertEqual(output.read_text(encoding="utf-8").strip(), created_value)
            self.assertEqual(
                created_body,
                {
                    "name": "immich-media-inbox",
                    "permissions": ["asset.read"],
                },
            )
            self.assertEqual(
                json.loads(metadata.read_text(encoding="utf-8"))["permissions"],
                ["asset.read"],
            )
            self.assertEqual(
                json.loads(metadata.read_text(encoding="utf-8"))["rollbackBackup"][
                    "filename"
                ],
                "new.sql.gz",
            )

    def test_bootstrap_revokes_key_after_incomplete_create_response(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            temp = Path(temporary)
            module = load_bootstrap_module()
            module.parse_args = lambda: argparse.Namespace(
                api_url="http://immich/api",
                source_container="helper",
                source_env="API_KEY",
                name="immich-media-inbox",
                output=temp / "immich_api_key",
                metadata_output=temp / "immich_api_key.json",
                require_new_backup=False,
                backup_timeout=60,
            )
            module.source_key_from_container = lambda container, name: "source-key"
            revoked: list[str] = []

            def fake_api_request(
                api_url: str,
                key: str,
                method: str,
                path: str,
                body: dict[str, Any] | None = None,
            ) -> Any:
                del api_url, key, body
                if method == "GET" and path == "/api-keys":
                    calls = getattr(fake_api_request, "list_calls", 0)
                    fake_api_request.list_calls = calls + 1
                    if calls == 0:
                        return []
                    return [
                        {
                            "id": "12345678-1234-1234-9234-123456789abc",
                            "name": "immich-media-inbox",
                        }
                    ]
                if method == "POST" and path == "/api-keys":
                    return {"apiKey": {"name": "immich-media-inbox"}}
                if method == "DELETE" and path.startswith("/api-keys/"):
                    revoked.append(path.rsplit("/", 1)[-1])
                    return None
                self.fail(f"unexpected API request: {method} {path}")

            module.api_request = fake_api_request
            with self.assertRaisesRegex(RuntimeError, "created key was revoked"):
                module.main()
            self.assertEqual(revoked, ["12345678-1234-1234-9234-123456789abc"])
            self.assertFalse((temp / "immich_api_key").exists())
            self.assertFalse((temp / "immich_api_key.json").exists())

    def test_seerr_export_refuses_unbacked_replacement_and_never_prints_key(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            temp = Path(temporary)
            settings = temp / "settings.json"
            output = temp / "seerr_api_key"
            settings.write_text(
                json.dumps({"main": {"apiKey": "first-secret"}}),
                encoding="utf-8",
            )
            command = [
                sys.executable,
                str(ROOT / "export-seerr-api-key"),
                "--settings",
                str(settings),
                "--output",
                str(output),
            ]
            first = subprocess.run(command, check=True, capture_output=True, text=True)
            self.assertNotIn("first-secret", first.stdout + first.stderr)
            settings.write_text(
                json.dumps({"main": {"apiKey": "second-secret"}}),
                encoding="utf-8",
            )
            refused = subprocess.run(
                command, check=False, capture_output=True, text=True
            )
            self.assertNotEqual(refused.returncode, 0)
            self.assertEqual(output.read_text(encoding="utf-8").strip(), "first-secret")
            self.assertNotIn("first-secret", refused.stdout + refused.stderr)
            self.assertNotIn("second-secret", refused.stdout + refused.stderr)
            checked = subprocess.run(
                command + ["--check"],
                check=True,
                capture_output=True,
                text=True,
            )
            self.assertIn("changed=true existing=true", checked.stdout)
            replaced = subprocess.run(
                command + ["--allow-replace"],
                check=True,
                capture_output=True,
                text=True,
            )
            self.assertNotIn("second-secret", replaced.stdout + replaced.stderr)
            self.assertEqual(
                output.read_text(encoding="utf-8").strip(), "second-secret"
            )


if __name__ == "__main__":
    unittest.main()
