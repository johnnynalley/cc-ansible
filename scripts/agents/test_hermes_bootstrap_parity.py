#!/usr/bin/env python3
"""Tests for OpenClaw evidence and native target parity validation."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).with_name("hermes-bootstrap-parity-validate.py")
ROOT = Path(__file__).parents[2]
REAL_CONTRACT = ROOT / "files/hermes/bootstrap-parity-contract.json"
SPEC = importlib.util.spec_from_file_location("hermes_bootstrap_parity", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE)


class BootstrapParityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.repo = self.root / "repo"
        self.source = self.root / "source"
        self.profile = self.root / "profile"
        self.repo.mkdir()
        self.source.mkdir()
        self.profile.mkdir()

        target_specs = [
            ("agents", "AGENTS.md", b"native agents\n"),
            ("soul", "SOUL.md", b"native soul\n"),
            (
                "heartbeat",
                "skills/operational-heartbeat/SKILL.md",
                b"native heartbeat\n",
            ),
            ("memory", "memories/MEMORY.md", b"native memory\n"),
            ("user", "memories/USER.md", b"native user\n"),
        ]
        self.native_targets = []
        for target_id, runtime, content in target_specs:
            runtime_path = self.profile / runtime
            runtime_path.parent.mkdir(parents=True, exist_ok=True)
            runtime_path.write_bytes(content)
            self.native_targets.append(
                {
                    "id": target_id,
                    "runtimePath": runtime,
                    "requirement": "nonempty-utf8",
                }
            )

        target_for = {
            "AGENTS.md": ["agents"],
            "CHARTER.md": ["agents", "soul"],
            "COMMS.md": ["agents"],
            "HEARTBEAT.md": ["agents", "heartbeat"],
            "IDENTITY.md": ["soul"],
            "JOB.md": ["soul"],
            "MEMORY.md": ["memory"],
            "MOTIVATIONS.md": ["soul"],
            "SOUL.md": ["soul"],
            "TOOLS.md": ["agents"],
            "USER.md": ["user"],
        }
        self.bootstrap_rows = []
        for name in sorted(MODULE.BOOTSTRAP_NAMES):
            content = f"legacy {name}\n".encode()
            (self.source / name).write_bytes(content)
            evidence = self.profile / "legacy-openclaw/workspace" / name
            evidence.parent.mkdir(parents=True, exist_ok=True)
            evidence.write_bytes(content)
            self.bootstrap_rows.append(
                {
                    "sourcePath": name,
                    "sha256": hashlib.sha256(content).hexdigest(),
                    "bytes": len(content),
                    "lines": content.count(b"\n"),
                    "disposition": "native-seeded-and-evidence" if name in {"MEMORY.md", "USER.md"} else "native-merged-and-evidence",
                    "nativeTargetIds": target_for[name],
                    "runtimeEvidence": f"legacy-openclaw/workspace/{name}",
                }
            )

        references = self.source / "references"
        references.mkdir()
        manifest = {
            "references": [
                {
                    "key": "active",
                    "path": "references/active.md",
                    "useWhen": "fixture",
                    "maintainWhen": "fixture",
                }
            ]
        }
        reference_content = {
            "references/active.md": b"active\n",
            "references/archive.md.bak": b"archive\n",
            "references/reference-manifest.json": json.dumps(manifest).encode(),
        }
        self.reference_rows = []
        for name, content in sorted(reference_content.items()):
            path = self.source / name
            path.write_bytes(content)
            evidence = self.profile / "legacy-openclaw/workspace" / name
            evidence.parent.mkdir(parents=True, exist_ok=True)
            evidence.write_bytes(content)
            self.reference_rows.append(
                {
                    "sourcePath": name,
                    "sha256": hashlib.sha256(content).hexdigest(),
                    "bytes": len(content),
                    "disposition": "semantic-reference" if name in {"references/active.md", "references/reference-manifest.json"} else "archival-evidence",
                    "runtimeEvidence": f"legacy-openclaw/workspace/{name}",
                }
            )

        self.contract = self.root / "contract.json"
        self.write_contract()

    def tearDown(self) -> None:
        self.temp.cleanup()

    def write_contract(self) -> None:
        semantic = sum(row["disposition"] == "semantic-reference" for row in self.reference_rows)
        payload = {
            "schemaVersion": 1,
            "mode": "complete-openclaw-bootstrap-reference-parity",
            "sourceRoot": str(self.source),
            "nativeLoader": {
                "profileRoot": "/var/lib/hermes/astra/.hermes/profiles/astra",
                "terminalCwd": "/var/lib/hermes/astra/.hermes/profiles/astra",
                "SOUL.md": "profile-root",
                "AGENTS.md": "terminal-cwd-profile-root",
                "MEMORY.md": "native-memory-store",
                "USER.md": "native-memory-store",
            },
            "nativeTargets": self.native_targets,
            "bootstrapSummary": {
                "files": len(self.bootstrap_rows),
                "bytes": sum(row["bytes"] for row in self.bootstrap_rows),
                "lines": sum(row["lines"] for row in self.bootstrap_rows),
            },
            "bootstrapFiles": self.bootstrap_rows,
            "referenceSummary": {
                "files": len(self.reference_rows),
                "bytes": sum(row["bytes"] for row in self.reference_rows),
                "semanticReferences": semantic,
                "archivalEvidence": len(self.reference_rows) - semantic,
                "aggregateSha256": MODULE.reference_aggregate(self.reference_rows),
                "aggregateAlgorithm": "sha256 of sorted '<file-sha256>  <path-within-references>\\n' rows",
            },
            "referenceFiles": self.reference_rows,
        }
        self.contract.write_text(json.dumps(payload), encoding="utf-8")

    def args(self, runtime: bool = False) -> argparse.Namespace:
        return argparse.Namespace(
            contract=self.contract,
            repo_root=self.repo,
            source_root=self.source,
            profile_root=self.profile if runtime else None,
            evidence_root=self.profile if runtime else None,
            runtime=runtime,
        )

    def test_static_contract_passes(self) -> None:
        result = MODULE.validate(self.args())
        self.assertEqual(result["bootstrapFiles"], 11)
        self.assertEqual(result["referenceFiles"], 3)

    def test_real_native_targets_have_no_repository_sources_or_hashes(self) -> None:
        contract = json.loads(REAL_CONTRACT.read_text(encoding="utf-8"))
        targets = {row["id"]: row for row in contract["nativeTargets"]}
        self.assertEqual(
            targets["astra-operational-heartbeat"]["runtimePath"],
            "skills/operational-heartbeat/SKILL.md",
        )
        self.assertEqual(targets["astra-memory"]["runtimePath"], "memories/MEMORY.md")
        self.assertEqual(targets["astra-user"]["runtimePath"], "memories/USER.md")
        for target in targets.values():
            self.assertEqual(
                set(target), {"id", "runtimePath", "requirement"}
            )
            self.assertEqual(target["requirement"], "nonempty-utf8")

    def test_runtime_contract_passes(self) -> None:
        result = MODULE.validate(self.args(runtime=True))
        self.assertTrue(result["runtime"])

    def test_bootstrap_hash_drift_fails(self) -> None:
        (self.source / "AGENTS.md").write_text("drift\n", encoding="utf-8")
        with self.assertRaisesRegex(MODULE.ParityError, "bootstrap-hash:AGENTS.md"):
            MODULE.validate(self.args())

    def test_unclassified_reference_fails(self) -> None:
        (self.source / "references/new.md").write_text("new\n", encoding="utf-8")
        with self.assertRaisesRegex(MODULE.ParityError, "reference-inventory"):
            MODULE.validate(self.args())

    def test_runtime_evidence_drift_fails(self) -> None:
        evidence = self.profile / "legacy-openclaw/workspace/CHARTER.md"
        evidence.write_text("drift\n", encoding="utf-8")
        with self.assertRaisesRegex(MODULE.ParityError, "bootstrap-evidence-hash:CHARTER.md"):
            MODULE.validate(self.args(runtime=True))

    def test_runtime_native_guidance_may_evolve_without_contract_change(self) -> None:
        (self.profile / "SOUL.md").write_text("drift\n", encoding="utf-8")
        (self.profile / "AGENTS.md").write_text(
            "native evolved guidance\n", encoding="utf-8"
        )
        result = MODULE.validate(self.args(runtime=True))
        self.assertTrue(result["runtime"])

    def test_runtime_native_memory_may_evolve(self) -> None:
        (self.profile / "memories/MEMORY.md").write_text(
            "native memory with durable learning\n", encoding="utf-8"
        )
        result = MODULE.validate(self.args(runtime=True))
        self.assertTrue(result["runtime"])

    def test_runtime_native_heartbeat_may_evolve(self) -> None:
        (self.profile / "skills/operational-heartbeat/SKILL.md").write_text(
            "native heartbeat with durable learning\n", encoding="utf-8"
        )
        result = MODULE.validate(self.args(runtime=True))
        self.assertTrue(result["runtime"])

    def test_runtime_does_not_require_any_repository_profile_source(self) -> None:
        self.assertEqual(list(self.repo.iterdir()), [])
        result = MODULE.validate(self.args(runtime=True))
        self.assertTrue(result["runtime"])

    def test_runtime_rejects_empty_native_target(self) -> None:
        (self.profile / "AGENTS.md").write_bytes(b"")
        with self.assertRaisesRegex(MODULE.ParityError, "runtime-target-empty:agents"):
            MODULE.validate(self.args(runtime=True))

    def test_runtime_rejects_invalid_native_target_encoding(self) -> None:
        (self.profile / "AGENTS.md").write_bytes(b"\xff")
        with self.assertRaisesRegex(
            MODULE.ParityError, "runtime-target-encoding:agents"
        ):
            MODULE.validate(self.args(runtime=True))

    def test_runtime_can_use_distinct_evidence_root(self) -> None:
        evidence_root = self.root / "evidence"
        evidence_root.mkdir()
        source = self.profile / "legacy-openclaw"
        source.rename(evidence_root / "legacy-openclaw")
        args = self.args(runtime=True)
        args.evidence_root = evidence_root
        result = MODULE.validate(args)
        self.assertTrue(result["runtime"])

    def test_runtime_can_audit_native_openclaw_root_view(self) -> None:
        evidence_root = self.root / "evidence-view"
        evidence_root.mkdir()
        source_root = evidence_root / "workspace"
        self.source.rename(source_root)
        args = self.args(runtime=True)
        args.source_root = source_root
        args.evidence_root = evidence_root
        result = MODULE.validate(args)
        self.assertTrue(result["runtime"])


if __name__ == "__main__":
    unittest.main()
