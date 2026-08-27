#!/usr/bin/env python3
"""Regression tests for the complete OpenClaw evidence projection."""

from __future__ import annotations

import importlib.util
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).parents[2]
SCRIPT = ROOT / "scripts/agents/hermes-openclaw-evidence.py"
SPEC = importlib.util.spec_from_file_location("hermes_openclaw_evidence", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def fixture(temporary: Path):
    source = temporary / "source"
    source.mkdir()
    (source / "AGENTS.md").write_text("legacy policy\n", encoding="utf-8")
    (source / "normal.txt").write_text("normal evidence\n", encoding="utf-8")
    (source / ".env").write_text("TOKEN=secret\n", encoding="utf-8")
    (source / "openclaw.json").write_text(
        json.dumps(
            {
                "gateway": {"port": 18789},
                "providers": {"example": {"apiKey": "sk-test-secret-value"}},
            }
        ),
        encoding="utf-8",
    )
    (source / "models.json").write_text(
        json.dumps(
            {
                "providers": {
                    "example": {
                        "apiKey": "sk-test-agent-model-secret",
                        "baseUrl": "https://example.invalid/v1",
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    state = source / "state" / "price-lookup"
    state.mkdir(parents=True)
    (state / "ebay_token_cache.json").write_text(
        json.dumps({"access_token": "active-secret"}), encoding="utf-8"
    )
    workspace = source / "workspace"
    workspace.mkdir()
    (workspace / "AGENTS.md").write_text("workspace policy\n", encoding="utf-8")
    backups = source / "backups" / "snapshot"
    backups.mkdir(parents=True)
    (backups / "credential.txt").write_text("secret\n", encoding="utf-8")
    (source / "outside-link").symlink_to(temporary / "outside")

    contract = json.loads(
        (ROOT / "files/hermes/openclaw-evidence-contract.json").read_text(
            encoding="utf-8"
        )
    )
    state = temporary / "state"
    contract["sourceRoot"] = str(source)
    contract["runtime"].update(
        {
            "stateRoot": str(state),
            "upperRoot": str(state / "upper"),
            "workRoot": str(state / "work"),
            "mergedRoot": str(state / "merged"),
            "manifestPath": str(state / "manifest.json"),
            "viewRoot": str(temporary / "view"),
            "profilePath": str(temporary / "profile" / "legacy-openclaw"),
        }
    )
    contract["requiredVisiblePaths"] = [
        "AGENTS.md",
        "workspace",
        "workspace/AGENTS.md",
    ]
    contract_path = temporary / "contract.json"
    contract_path.write_text(json.dumps(contract), encoding="utf-8")
    loaded, rules, patterns = MODULE.load_contract(contract_path)
    return source, contract_path, loaded, rules, patterns


class OpenClawEvidenceTests(unittest.TestCase):
    def test_real_contract_requires_complete_source_preservation(self):
        contract, rules, _patterns = MODULE.load_contract(
            ROOT / "files/hermes/openclaw-evidence-contract.json"
        )
        self.assertEqual(contract["sourceRoot"], "/home/johnny/.openclaw")
        self.assertEqual(
            contract["completeness"]["defaultDisposition"], "visible-readonly"
        )
        self.assertTrue(contract["completeness"]["everySourcePathInventoried"])
        self.assertFalse(contract["completeness"]["sourceMutationAllowed"])
        self.assertFalse(contract["completeness"]["sourceContentCopied"])
        self.assertFalse(contract["completeness"]["sourceSymlinksFollowed"])
        self.assertFalse(contract["completeness"]["unclassifiedOmissionAllowed"])
        rule_ids = {rule.rule_id for rule in rules}
        self.assertTrue(
            {
                "root-backups",
                "credential-store",
                "secret-store",
                "device-identity",
                "browser-profile",
                "environment-files",
                "agent-auth-profiles",
                "agent-auth-state",
                "agent-model-config",
                "token-cache-files",
                "openclaw-config",
            }.issubset(rule_ids)
        )

    def test_every_source_path_is_accounted_without_following_links(self):
        with tempfile.TemporaryDirectory() as directory:
            source, _path, _contract, rules, _patterns = fixture(Path(directory))
            manifest = MODULE.inventory(source, rules)
            records = {row["path"]: row for row in manifest["paths"]}

            expected = {
                path.relative_to(source).as_posix()
                for path in source.rglob("*")
            }
            self.assertEqual(set(records), expected)
            self.assertEqual(records["normal.txt"]["classification"], "visible")
            self.assertEqual(records[".env"]["classification"], "redacted")
            self.assertEqual(records["models.json"]["strategy"], "sanitized-json")
            self.assertEqual(
                records["state/price-lookup/ebay_token_cache.json"]["classification"],
                "redacted",
            )
            self.assertEqual(records["backups"]["strategy"], "opaque-inventory")
            self.assertEqual(records["outside-link"]["kind"], "symlink")
            self.assertEqual(records["outside-link"]["classification"], "redacted")

    def test_prepare_replaces_secrets_links_and_backups_with_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            source, _path, contract, rules, patterns = fixture(Path(directory))
            manifest = MODULE.inventory(source, rules)
            with mock.patch.object(MODULE.os, "geteuid", return_value=0), mock.patch.object(
                MODULE.os, "setxattr"
            ):
                result = MODULE.prepare(contract, rules, patterns, manifest)

            upper = Path(contract["runtime"]["upperRoot"])
            self.assertEqual(result["opaqueTrees"], 1)
            marker = json.loads((upper / ".env").read_text(encoding="utf-8"))
            self.assertEqual(marker["status"], "redacted")
            self.assertFalse(marker["contentAvailableToAstra"])
            link = json.loads((upper / "outside-link").read_text(encoding="utf-8"))
            self.assertEqual(link["sourceKind"], "symlink")
            backup = json.loads(
                (upper / "backups/REDACTED-INVENTORY.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(backup["sourcePathCount"], 3)
            sanitized = json.loads(
                (upper / "openclaw.json").read_text(encoding="utf-8")
            )
            self.assertEqual(sanitized["gateway"]["port"], 18789)
            self.assertEqual(
                sanitized["providers"]["example"]["apiKey"], "[REDACTED]"
            )
            self.assertNotIn("sk-test-secret-value", json.dumps(sanitized))
            model_config = json.loads(
                (upper / "models.json").read_text(encoding="utf-8")
            )
            self.assertEqual(
                model_config["providers"]["example"]["apiKey"], "[REDACTED]"
            )
            self.assertEqual(
                model_config["providers"]["example"]["baseUrl"],
                "https://example.invalid/v1",
            )
            token_cache = json.loads(
                (upper / "state/price-lookup/ebay_token_cache.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(token_cache["status"], "redacted")

    def test_audit_detects_source_drift(self):
        with tempfile.TemporaryDirectory() as directory:
            source, _path, contract, rules, _patterns = fixture(Path(directory))
            manifest = MODULE.inventory(source, rules)
            manifest_path = Path(contract["runtime"]["manifestPath"])
            MODULE._atomic_json(manifest_path, manifest)
            self.assertEqual(MODULE.audit(contract, rules, manifest_path)["status"], "ok")

            (source / "normal.txt").write_text(
                "changed evidence with a new size\n", encoding="utf-8"
            )
            self.assertEqual(
                MODULE.audit(contract, rules, manifest_path)["status"], "drift"
            )

    def test_view_verifier_requires_readonly_complete_projection(self):
        with tempfile.TemporaryDirectory() as directory:
            source, _path, contract, rules, patterns = fixture(Path(directory))
            manifest = MODULE.inventory(source, rules)
            with mock.patch.object(MODULE.os, "geteuid", return_value=0), mock.patch.object(
                MODULE.os, "setxattr"
            ):
                MODULE.prepare(contract, rules, patterns, manifest)

            # Build the fixture's merged shape without exercising kernel overlay/FUSE.
            view = Path(directory) / "synthetic-view"
            view.mkdir()
            upper = Path(contract["runtime"]["upperRoot"])
            for record in manifest["paths"]:
                relative = record["path"]
                destination = view / relative
                upper_path = upper / relative
                if record["classification"] == "visible":
                    source_path = source / relative
                    if record["kind"] == "directory":
                        destination.mkdir(parents=True, exist_ok=True)
                    else:
                        destination.parent.mkdir(parents=True, exist_ok=True)
                        destination.write_bytes(source_path.read_bytes())
                elif upper_path.exists() and not destination.exists():
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    if upper_path.is_dir():
                        destination.mkdir(parents=True, exist_ok=True)
                        marker = upper_path / "REDACTED-INVENTORY.json"
                        (destination / marker.name).write_bytes(marker.read_bytes())
                    else:
                        destination.write_bytes(upper_path.read_bytes())
            (view / ".hermes-evidence-manifest.json").write_bytes(
                (upper / ".hermes-evidence-manifest.json").read_bytes()
            )
            readonly = mock.Mock(f_flag=os.ST_RDONLY)
            with mock.patch.object(MODULE.os, "statvfs", return_value=readonly):
                result = MODULE.verify_view(contract, rules, view)
            self.assertEqual(result["status"], "ok")
            self.assertTrue(result["readOnly"])
            self.assertEqual(result["paths"], manifest["summary"]["paths"])

            with mock.patch.object(
                MODULE.os, "statvfs", return_value=mock.Mock(f_flag=0)
            ):
                with self.assertRaisesRegex(MODULE.EvidenceError, "view-not-readonly"):
                    MODULE.verify_view(contract, rules, view)

    def test_contract_rejects_runtime_state_inside_source(self):
        with tempfile.TemporaryDirectory() as directory:
            source, contract_path, _contract, _rules, _patterns = fixture(Path(directory))
            contract = json.loads(contract_path.read_text(encoding="utf-8"))
            state = source / "generated"
            contract["runtime"].update(
                {
                    "stateRoot": str(state),
                    "upperRoot": str(state / "upper"),
                    "workRoot": str(state / "work"),
                    "mergedRoot": str(state / "merged"),
                    "manifestPath": str(state / "manifest.json"),
                }
            )
            contract_path.write_text(json.dumps(contract), encoding="utf-8")
            with self.assertRaisesRegex(
                MODULE.EvidenceError, "source-and-state-roots-overlap"
            ):
                MODULE.load_contract(contract_path)

    def test_manifest_path_must_be_exact_generated_location(self):
        with tempfile.TemporaryDirectory() as directory:
            source, _path, contract, rules, patterns = fixture(Path(directory))
            manifest = MODULE.inventory(source, rules)
            contract["runtime"]["manifestPath"] = str(
                Path(contract["runtime"]["stateRoot"]) / "nested/manifest.json"
            )
            with mock.patch.object(MODULE.os, "geteuid", return_value=0):
                with self.assertRaisesRegex(
                    MODULE.EvidenceError, "generated-manifest.json-unexpected-path"
                ):
                    MODULE.prepare(contract, rules, patterns, manifest)

    def test_playbook_is_approval_gated_and_source_preserving(self):
        text = (ROOT / "playbooks/agents/hermes-openclaw-evidence.yml").read_text(
            encoding="utf-8"
        )
        for required in (
            "hermes_openclaw_evidence_mode in ['disabled', 'converge']",
            "hermes_openclaw_evidence_confirmation == hermes_openclaw_evidence_required_confirmation",
            "Plan every preserved OpenClaw path before mutation",
            "Validate exact OpenClaw bootstrap and reference source pins",
            "hermes-openclaw-evidence.service.j2",
            "hermes-openclaw-evidence-audit.service.j2",
            "hermes-openclaw-evidence-audit.timer.j2",
            "hermes-gateway-openclaw-evidence.conf.j2",
            "Back up prior complete evidence state and units",
            "Install complete evidence mount dependencies",
            "hermes_openclaw_evidence_view_parent",
            "Verify complete projected view as Astra",
            "Verify exact bootstrap and references inside Astra's namespace",
            "/usr/bin/nsenter",
            "Restore prior complete evidence state and units",
            "Restore prior inactive evidence projection enablement",
            "Restore prior inactive evidence timer enablement",
            "Audit existing complete evidence before convergence",
            "Verify existing complete evidence view as Astra",
            "Decide whether complete evidence requires regeneration",
            "Decide whether Astra requires one namespace restart",
            "Create persistent complete evidence runtime roots",
            "Create complete evidence mount roots after projection stop",
            "hermes_openclaw_evidence_projection_restart_required",
            "hermes_openclaw_evidence_gateway_restart_required",
        ):
            self.assertIn(required, text)
        self.assertLess(
            text.index("Back up prior complete evidence state and units"),
            text.index("Install complete evidence mount dependencies"),
        )
        self.assertIn("--one-file-system", text)
        self.assertLess(
            text.index("Restore Astra Gateway after evidence convergence"),
            text.index("Verify exact bootstrap and references inside Astra's namespace"),
        )
        self.assertNotIn("remote_src: true", text)
        self.assertNotIn("sourceContentCopied: true", text)
        self.assertIn(
            'src: "{{ playbook_dir }}/../../templates/hermes/{{ item.source }}"',
            text,
        )
        self.assertIn(
            "when: hermes_openclaw_evidence_unit_changes.changed | bool",
            text,
        )
        self.assertGreaterEqual(
            text.count("hermes_openclaw_evidence_gateway_restart_required"),
            3,
        )
        persistent_roots = text[
            text.index("Create persistent complete evidence runtime roots") :
            text.index("Deploy complete OpenClaw evidence contract")
        ]
        self.assertNotIn(
            'hermes_openclaw_evidence_contract.runtime.mergedRoot', persistent_roots
        )
        self.assertNotIn(
            'hermes_openclaw_evidence_contract.runtime.viewRoot', persistent_roots
        )
        mount_roots = text[
            text.index("Create complete evidence mount roots after projection stop") :
            text.index("Start complete read-only OpenClaw evidence projection")
        ]
        self.assertIn(
            'hermes_openclaw_evidence_contract.runtime.mergedRoot', mount_roots
        )
        self.assertIn(
            'hermes_openclaw_evidence_contract.runtime.viewRoot', mount_roots
        )
        self.assertIn(
            "when: hermes_openclaw_evidence_projection_restart_required | bool",
            mount_roots,
        )
        rollback = text[text.index("rescue:") :]
        self.assertEqual(
            rollback.count(
                "when: hermes_openclaw_evidence_gateway_was_active | bool"
            ),
            2,
        )
        post_runtime = text[
            text.index("Verify exact bootstrap and references inside Astra's namespace") :
            text.index("Parse Astra bootstrap and reference runtime verification")
        ]
        self.assertNotIn("--evidence-root", post_runtime)

    def test_service_projects_overlay_through_readonly_bindfs(self):
        service = (
            ROOT / "templates/hermes/hermes-openclaw-evidence.service.j2"
        ).read_text(encoding="utf-8")
        self.assertIn("/usr/bin/mount -t overlay overlay", service)
        self.assertIn("/usr/bin/bindfs -f -r", service)
        self.assertIn("--perms=0000:u=rD", service)
        self.assertIn("--mirror-only=", service)
        self.assertIn("ExecStop=/usr/bin/fusermount3 -u", service)
        self.assertIn(
            "CapabilityBoundingSet=CAP_SYS_ADMIN CAP_SETUID CAP_SETGID CAP_DAC_READ_SEARCH",
            service,
        )
        self.assertIn("ExecStartPre=+{{ hermes_openclaw_evidence_script_live }} prepare", service)
        self.assertIn("ExecStartPre=+/usr/bin/mount -t overlay overlay", service)
        for excluded_capability in (
            "CAP_CHOWN",
            "CAP_DAC_OVERRIDE",
            "CAP_FOWNER",
            "CAP_FSETID",
            "CAP_MKNOD",
        ):
            self.assertNotIn(excluded_capability, service)
        self.assertIn("Documentation=file:", service)
        self.assertIn("User=root", service)
        self.assertIn(
            "Group={{ hermes_openclaw_evidence_contract.runtime.profileGroup }}",
            service,
        )
        self.assertIn("RuntimeDirectory=hermes-openclaw-evidence", service)
        self.assertIn("RuntimeDirectoryMode=0710", service)
        view_root_create = (
            "ExecStartPre=+/usr/bin/install -d -o root -g "
            "{{ hermes_openclaw_evidence_contract.runtime.profileGroup }} "
            "-m 0710 "
            "{{ hermes_openclaw_evidence_contract.runtime.viewRoot }}"
        )
        self.assertIn(view_root_create, service)
        self.assertLess(
            service.index(view_root_create),
            service.index("ExecStartPre=-/usr/bin/fusermount3"),
        )
        for namespace_directive in (
            "ProtectSystem=",
            "PrivateMounts=",
            "ProtectHome=",
            "ProtectProc=",
        ):
            self.assertNotIn(namespace_directive, service)

        timer = (
            ROOT / "templates/hermes/hermes-openclaw-evidence-audit.timer.j2"
        ).read_text(encoding="utf-8")
        playbook = (
            ROOT / "playbooks/agents/hermes-openclaw-evidence.yml"
        ).read_text(encoding="utf-8")
        self.assertIn("OnActiveSec=1h", timer)
        self.assertIn("OnUnitActiveSec=6h", timer)
        self.assertNotIn("OnBootSec=", timer)
        self.assertIn(
            "Decide whether the evidence audit timer requires rescheduling",
            playbook,
        )
        self.assertIn("'SubState=waiting' not in", playbook)
        self.assertIn(
            "if hermes_openclaw_evidence_audit_timer_restart_required | bool",
            playbook,
        )

        dropin = (
            ROOT / "templates/hermes/hermes-gateway-openclaw-evidence.conf.j2"
        ).read_text(encoding="utf-8")
        self.assertIn("Requires={{ hermes_openclaw_evidence_service }}", dropin)
        self.assertIn("BindReadOnlyPaths=", dropin)
        self.assertIn("/workspace/AGENTS.md", dropin)
        self.assertIn("/workspace/references", dropin)
        self.assertIn("hermes_bootstrap_parity_validator_live", dropin)
        self.assertIn("--runtime", dropin)

        audit = (
            ROOT / "templates/hermes/hermes-openclaw-evidence-audit.service.j2"
        ).read_text(encoding="utf-8")
        self.assertIn("hermes_bootstrap_parity_validator_live", audit)
        self.assertIn("--evidence-root", audit)
        self.assertIn("verify-view", audit)
        self.assertIn("--view-root", audit)
        self.assertNotIn("evidence_script_live }} audit", audit)
        self.assertIn("ProtectHome=true", audit)
        self.assertIn(
            "User={{ hermes_openclaw_evidence_contract.runtime.profileUser }}",
            audit,
        )
        self.assertIn(
            "Group={{ hermes_openclaw_evidence_contract.runtime.profileGroup }}",
            audit,
        )

    def test_preserved_source_is_an_offhost_readonly_platform_mount(self):
        mounts = (
            ROOT / "inventory/host_vars/jn-t14s-lin/mounts.yml"
        ).read_text(encoding="utf-8")
        backup = (
            ROOT / "inventory/host_vars/jn-t14s-lin/backup.yml"
        ).read_text(encoding="utf-8")
        self.assertIn("path: /home/johnny/.openclaw", mounts)
        self.assertIn("/srv/live-rollbacks/jn-t14s-lin/hermes-openclaw-evidence/", mounts)
        self.assertIn("fstype: squashfs", mounts)
        for required_option in (
            "loop",
            "ro",
            "nosuid",
            "nodev",
            "noexec",
            "_netdev",
            "x-systemd.requires-mounts-for=/srv/live-rollbacks",
        ):
            self.assertIn(required_option, mounts)
        self.assertIn("- /home/johnny/.openclaw", backup)


if __name__ == "__main__":
    unittest.main()
