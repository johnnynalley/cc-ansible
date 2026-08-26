#!/usr/bin/env python3
"""Tests for isolated profile LCM source selection and output boundaries."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).parents[2]
SOURCE = ROOT / "scripts/agents/hermes-profile-lcm-import.py"
SPEC = importlib.util.spec_from_file_location("hermes_profile_lcm_import", SOURCE)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class Result:
    def __init__(self, **overrides):
        self.values = {
            "conversations": 1,
            "scanned": 2,
            "eligible": 2,
            "would_import": 2,
            "imported": 0,
            "skipped_existing": 0,
            "skipped_empty": 0,
            "invalid_rows": 0,
            "warnings": [],
            "import_id": "rigel-v1",
        }
        self.values.update(overrides)

    def to_dict(self):
        return self.values


class ProfileLcmImportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.source_dir = self.root / "sessions"
        self.source_dir.mkdir()
        (self.source_dir / "one.jsonl").write_text("canonical\n")
        (self.source_dir / "one.trajectory.jsonl").write_text("trajectory\n")
        self.importer = self.root / "importer.py"
        self.importer.write_text("def import_jsonl_sessions(**kwargs): pass\n")

    def tearDown(self):
        self.temp.cleanup()

    def args(self):
        return types.SimpleNamespace(
            importer=self.importer,
            source_dir=self.source_dir,
            target_db=self.root / "lcm.db",
            namespace="openclaw-rigel-jsonl",
            agent="rigel",
            import_id="rigel-v1",
            apply=False,
            include_manifest=None,
            allow_invalid_record=[],
        )

    def selection_manifest(self, approved: list[str]) -> Path:
        source = MODULE.canonical_source_manifest(self.source_dir)
        path = self.root / "selection.json"
        path.write_text(
            json.dumps(
                {
                    "schemaVersion": 1,
                    "status": "approved-public-subset",
                    "sourceFileCount": len(source.files),
                    "sourceBytes": source.bytes,
                    "sourceManifestSha256": source.sha256,
                    "sessionIndexManifestSha256": "1" * 64,
                    "policySha256": "2" * 64,
                    "approvedFileCount": len(approved),
                    "approvedFiles": approved,
                },
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        return path

    def test_selects_only_canonical_sessions_and_hashes_source(self):
        manifest = MODULE.canonical_source_manifest(self.source_dir)
        self.assertEqual([path.name for path in manifest.files], ["one.jsonl"])
        self.assertEqual(manifest.trajectory_files, 1)
        self.assertEqual(manifest.bytes, len("canonical\n"))
        self.assertEqual(len(manifest.sha256), 64)

    def test_rejects_nested_or_linked_session_sources(self):
        nested = self.source_dir / "nested"
        nested.mkdir()
        (nested / "two.jsonl").write_text("x\n")
        with self.assertRaisesRegex(MODULE.ImportBoundaryError, "nested-session-jsonl"):
            MODULE.canonical_source_manifest(self.source_dir)
        (nested / "two.jsonl").unlink()
        nested.rmdir()
        (self.source_dir / "linked.jsonl").symlink_to(self.source_dir / "one.jsonl")
        with self.assertRaisesRegex(MODULE.ImportBoundaryError, "session-not-regular"):
            MODULE.canonical_source_manifest(self.source_dir)

    def test_emits_content_free_counts_and_omits_source_paths(self):
        fake = types.SimpleNamespace(
            import_jsonl_sessions=mock.Mock(return_value=Result())
        )
        with mock.patch.object(
            MODULE, "load_importer", return_value=fake
        ), mock.patch.object(
            MODULE,
            "enable_content_tool_call_id_compat",
            return_value="content-tool-call-id-fallback",
        ):
            output = MODULE.execute(self.args())
        encoded = json.dumps(output)
        self.assertEqual(output["status"], "ready")
        self.assertEqual(output["sourceFileCount"], 1)
        self.assertNotIn(str(self.source_dir), encoded)
        self.assertNotIn("canonical", encoded)
        files = fake.import_jsonl_sessions.call_args.kwargs["files"]
        self.assertEqual([path.name for path in files], ["one.jsonl"])

    def test_exact_invalid_record_allowance_uses_ephemeral_copy(self):
        source = self.source_dir / "one.jsonl"
        original = '{"ok":1}\nmalformed preserved record\n{"ok":2}\n'
        source.write_text(original, encoding="utf-8")
        invalid_line = "malformed preserved record\n"
        allowance_value = ":".join(
            (
                hashlib.sha256(source.name.encode("utf-8")).hexdigest(),
                "2",
                str(len(invalid_line)),
                hashlib.sha256(invalid_line.encode("utf-8")).hexdigest(),
            )
        )
        allowances = MODULE.parse_invalid_record_allowances([allowance_value])
        staging = self.root / "staging"
        staging.mkdir(mode=0o700)
        staged, excluded = MODULE.stage_allowed_invalid_records(
            (source,), allowances, staging
        )
        self.assertEqual(excluded, 1)
        self.assertEqual(source.read_text(encoding="utf-8"), original)
        self.assertEqual(staged[0].read_text(encoding="utf-8"), '{"ok":1}\n{"ok":2}\n')
        self.assertEqual(staged[0].stat().st_mode & 0o777, 0o600)

        drifted = allowance_value.rsplit(":", 1)[0] + ":" + ("0" * 64)
        second_staging = self.root / "second-staging"
        second_staging.mkdir(mode=0o700)
        with self.assertRaisesRegex(
            MODULE.ImportBoundaryError, "invalid-record-hash-drift"
        ):
            MODULE.stage_allowed_invalid_records(
                (source,),
                MODULE.parse_invalid_record_allowances([drifted]),
                second_staging,
            )

    def test_hash_pinned_manifest_selects_only_approved_public_sources(self):
        (self.source_dir / "two.jsonl").write_text("second\n", encoding="utf-8")
        args = self.args()
        args.include_manifest = self.selection_manifest(["one.jsonl"])
        fake = types.SimpleNamespace(import_jsonl_sessions=mock.Mock(return_value=Result()))
        with mock.patch.object(
            MODULE, "load_importer", return_value=fake
        ), mock.patch.object(
            MODULE, "enable_content_tool_call_id_compat", return_value="native"
        ):
            output = MODULE.execute(args)
        selected = fake.import_jsonl_sessions.call_args.kwargs["files"]
        self.assertEqual([path.name for path in selected], ["one.jsonl"])
        self.assertEqual(output["sourceFileCount"], 2)
        self.assertEqual(output["selectedFileCount"], 1)
        self.assertEqual(len(output["includeManifestSha256"]), 64)

    def test_manifest_rejects_source_or_name_drift(self):
        manifest = self.selection_manifest(["one.jsonl"])
        (self.source_dir / "one.jsonl").write_text("changed\n", encoding="utf-8")
        with self.assertRaisesRegex(MODULE.ImportBoundaryError, "include-manifest-source"):
            MODULE.load_source_selection(
                manifest, MODULE.canonical_source_manifest(self.source_dir)
            )

        source = MODULE.canonical_source_manifest(self.source_dir)
        payload = json.loads(manifest.read_text(encoding="utf-8"))
        payload["sourceBytes"] = source.bytes
        payload["sourceManifestSha256"] = source.sha256
        payload["approvedFiles"] = ["../one.jsonl"]
        manifest.write_text(json.dumps(payload), encoding="utf-8")
        with self.assertRaisesRegex(MODULE.ImportBoundaryError, "include-manifest-name-boundary"):
            MODULE.load_source_selection(manifest, source)

    def test_fails_closed_on_invalid_rows_or_warnings(self):
        for result, message in (
            (Result(invalid_rows=1), "invalid-source-rows"),
            (Result(warnings=["one.jsonl:1: unsupported row"]), "source-warnings"),
        ):
            fake = types.SimpleNamespace(
                import_jsonl_sessions=mock.Mock(return_value=result)
            )
            with self.subTest(message=message), mock.patch.object(
                MODULE, "load_importer", return_value=fake
            ), mock.patch.object(
                MODULE,
                "enable_content_tool_call_id_compat",
                return_value="content-tool-call-id-fallback",
            ):
                with self.assertRaisesRegex(MODULE.ImportBoundaryError, message):
                    MODULE.execute(self.args())

    def test_content_tool_call_id_compat_is_narrow_and_self_retiring(self):
        def parse(item, allow_id_fallback=False):
            if item.get("type") != "toolCall" or "name" not in item:
                return None
            if "tool_call_id" in item:
                call_id = item["tool_call_id"]
            elif allow_id_fallback and "id" in item:
                call_id = item["id"]
            else:
                return None
            if "arguments" not in item:
                return None
            return {"id": call_id, "function": {"name": item["name"]}}

        importer = types.SimpleNamespace(
            JSONL_TOOL_CALL_TYPES={"toolCall"},
            JSONL_OPENCLAW_TOOL_CALL_TYPES={"toolCall"},
            _jsonl_openai_tool_call=parse,
            _jsonl_string_type=lambda value: value if isinstance(value, str) else None,
            _jsonl_content_item_has_malformed_tool_call_type=lambda item: False,
        )
        mode = MODULE.enable_content_tool_call_id_compat(importer)
        self.assertEqual(mode, "content-tool-call-id-fallback")
        content = [
            {
                "type": "toolCall",
                "id": "call-1",
                "name": "test",
                "arguments": {},
            }
        ]
        self.assertEqual(importer._jsonl_tool_calls_from_content(content)[0]["id"], "call-1")
        self.assertEqual(importer._jsonl_malformed_tool_call_content_types(content), [])

        native = types.SimpleNamespace(
            _jsonl_openai_tool_call=lambda item, allow_id_fallback=False: {"id": "native"}
        )
        self.assertEqual(MODULE.enable_content_tool_call_id_compat(native), "native")

    def test_malformed_shape_diagnostic_omits_values(self):
        source = self.source_dir / "two.jsonl"
        source.write_text(
            json.dumps(
                {
                    "type": "message",
                    "message": {
                        "role": "assistant",
                        "content": [
                            {
                                "type": "toolCall",
                                "id": "secret-id",
                                "name": "secret-tool",
                            }
                        ],
                    },
                }
            )
            + "\n"
        )
        importer = types.SimpleNamespace(
            JSONL_TOOL_CALL_TYPES={"toolCall"},
            _jsonl_row_message=lambda row: row["message"],
            _jsonl_effective_row_type=lambda row, message: row["type"],
            _jsonl_role=lambda message, row_type: message["role"],
            _jsonl_content=lambda message, role: message["content"],
            _jsonl_malformed_tool_call_content_types=lambda content: ["toolCall"],
        )
        counts = MODULE.malformed_tool_call_shapes(
            importer, (source,)
        )
        encoded = json.dumps(counts)
        self.assertIn(
            "type=toolCall;nested=False;id=True;idKeys=id;name=True;"
            "arguments=False;argumentKeys=none",
            encoded,
        )
        self.assertNotIn("secret-id", encoded)
        self.assertNotIn("secret-tool", encoded)

        invalid = self.source_dir / "secret-session-name.jsonl"
        invalid.write_text("secret malformed source value\n", encoding="utf-8")
        counts = MODULE.malformed_tool_call_shapes(importer, (invalid,))
        encoded = json.dumps(counts)
        self.assertIn(
            hashlib.sha256(invalid.name.encode("utf-8")).hexdigest(), encoded
        )
        self.assertIn("line=1", encoded)
        self.assertNotIn(invalid.name, encoded)
        self.assertNotIn("secret malformed source value", encoded)


if __name__ == "__main__":
    unittest.main()
