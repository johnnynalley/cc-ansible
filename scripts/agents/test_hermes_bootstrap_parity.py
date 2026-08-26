#!/usr/bin/env python3
"""Tests for exact OpenClaw bootstrap/reference parity validation."""

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

        native_files = {
            "native/AGENTS.md": b"native agents\n",
            "native/SOUL.md": b"native soul\n",
            "native/heartbeat.md": b"native heartbeat\n",
        }
        for relative, content in native_files.items():
            path = self.repo / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
        for relative in ("vault/MEMORY.md.vault", "vault/USER.md.vault"):
            path = self.repo / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"$ANSIBLE_VAULT;1.2;AES256;default\nfixture\n")

        target_specs = [
            ("agents", "plain", "native/AGENTS.md", "exact", "AGENTS.md", native_files["native/AGENTS.md"]),
            ("soul", "plain", "native/SOUL.md", "exact", "SOUL.md", native_files["native/SOUL.md"]),
            ("heartbeat", "plain", "native/heartbeat.md", "seeded-mutable", "skills/operational-heartbeat/SKILL.md", native_files["native/heartbeat.md"]),
            ("memory", "ansible-vault-plaintext", "vault/MEMORY.md.vault", "seeded-mutable", "MEMORY.md", b"native memory\n"),
            ("user", "ansible-vault-plaintext", "vault/USER.md.vault", "seeded-mutable", "USER.md", b"native user\n"),
        ]
        self.target_pins = []
        for target_id, kind, source, runtime_policy, runtime, plaintext in target_specs:
            runtime_path = self.profile / runtime
            runtime_path.parent.mkdir(parents=True, exist_ok=True)
            runtime_path.write_bytes(plaintext)
            self.target_pins.append(
                {
                    "id": target_id,
                    "kind": kind,
                    "sourcePath": source,
                    "sha256": hashlib.sha256(plaintext).hexdigest(),
                    "runtimePolicy": runtime_policy,
                    "runtimePath": runtime,
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
            "managedTargetPins": self.target_pins,
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

    def test_real_runtime_pins_use_native_profile_locations(self) -> None:
        contract = json.loads(REAL_CONTRACT.read_text(encoding="utf-8"))
        pins = {row["id"]: row for row in contract["managedTargetPins"]}
        self.assertEqual(
            pins["astra-operational-heartbeat"]["runtimePath"],
            "skills/operational-heartbeat/SKILL.md",
        )
        heartbeat_source = ROOT / pins["astra-operational-heartbeat"]["sourcePath"]
        self.assertEqual(
            pins["astra-operational-heartbeat"]["sha256"],
            hashlib.sha256(heartbeat_source.read_bytes()).hexdigest(),
        )
        self.assertEqual(
            pins["astra-operational-heartbeat"]["runtimePolicy"],
            "seeded-mutable",
        )
        self.assertEqual(
            pins["astra-memory"]["runtimePath"], "memories/MEMORY.md"
        )
        self.assertEqual(pins["astra-memory"]["runtimePolicy"], "seeded-mutable")
        self.assertEqual(pins["astra-user"]["runtimePath"], "memories/USER.md")
        self.assertEqual(pins["astra-user"]["runtimePolicy"], "seeded-mutable")

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

    def test_runtime_native_target_drift_fails(self) -> None:
        (self.profile / "SOUL.md").write_text("drift\n", encoding="utf-8")
        with self.assertRaisesRegex(MODULE.ParityError, "runtime-target-hash:soul"):
            MODULE.validate(self.args(runtime=True))

    def test_runtime_seeded_memory_may_evolve(self) -> None:
        (self.profile / "MEMORY.md").write_text(
            "native memory with durable learning\n", encoding="utf-8"
        )
        result = MODULE.validate(self.args(runtime=True))
        self.assertTrue(result["runtime"])

    def test_runtime_seeded_plain_heartbeat_may_evolve(self) -> None:
        (self.profile / "skills/operational-heartbeat/SKILL.md").write_text(
            "native heartbeat with durable learning\n", encoding="utf-8"
        )
        result = MODULE.validate(self.args(runtime=True))
        self.assertTrue(result["runtime"])

    def test_runtime_does_not_require_encrypted_seed_source_access(self) -> None:
        (self.repo / "vault/MEMORY.md.vault").unlink()
        (self.repo / "vault/USER.md.vault").unlink()
        result = MODULE.validate(self.args(runtime=True))
        self.assertTrue(result["runtime"])

    def test_runtime_does_not_require_plain_managed_source_access(self) -> None:
        for path in ("native/AGENTS.md", "native/SOUL.md", "native/heartbeat.md"):
            (self.repo / path).unlink()
        result = MODULE.validate(self.args(runtime=True))
        self.assertTrue(result["runtime"])

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
