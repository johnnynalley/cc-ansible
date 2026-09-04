#!/usr/bin/env python3

import importlib.util
import json
from pathlib import Path
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/agents/hermes-ansible-ownership-audit.py"
CONTRACT = ROOT / "files/hermes/ansible-ownership-contract.json"
SPEC = importlib.util.spec_from_file_location("hermes_ownership_audit", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


class HermesAnsibleOwnershipAuditTests(unittest.TestCase):
    def setUp(self):
        self.contract = MODULE.load_contract(CONTRACT)

    def test_repository_has_no_unclassified_hermes_path_reference(self):
        result = MODULE.audit(ROOT, self.contract)
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["unclassifiedCount"], 0)
        self.assertGreaterEqual(result["sourceCount"], 29)
        self.assertGreaterEqual(result["referenceCount"], 500)

    def test_profile_native_state_uses_most_specific_preserve_rule(self):
        rules = self.contract["rules"]
        for profile in ("astra", "dubble", "rigel"):
            value = (
                f"/var/lib/hermes/{profile}/.hermes/profiles/{profile}/"
                "cron/jobs.json"
            )
            rule = MODULE.classify(value, rules)
            self.assertIsNotNone(rule)
            self.assertEqual(rule["classification"], "mutable-native")
            self.assertEqual(rule["normalConvergence"], "preserve")

    def test_retired_root_profile_state_uses_specific_retirement_rules(self):
        rules = self.contract["rules"]
        for profile in ("astra", "dubble", "rigel"):
            for suffix in ("config.yaml", "skills/example/SKILL.md"):
                rule = MODULE.classify(
                    f"/etc/hermes/{profile}/{suffix}",
                    rules,
                )
                self.assertIsNotNone(rule)
                self.assertEqual(rule["classification"], "legacy-retirement")

    def test_normal_convergence_cannot_publish_mutable_profile_state(self):
        normal_playbooks = (
            "hermes-arr-api.yml",
            "hermes-automation.yml",
            "hermes-compose-admin.yml",
            "hermes-docker-inventory.yml",
            "hermes-fleet-admin.yml",
            "hermes-host-admin.yml",
            "hermes-memory-continuity.yml",
            "hermes-production-runtime.yml",
            "hermes-profile-memory-continuity.yml",
            "hermes-replacement-node-rehearsal.yml",
            "hermes-rigel-astra-liaison.yml",
            "hermes-shadow.yml",
        )
        forbidden = (
            "managed-policy.sha256",
            "hermes-managed-config.yaml.j2",
            "/etc/hermes/astra/config.yaml",
            "/etc/hermes/dubble/config.yaml",
            "/etc/hermes/rigel/config.yaml",
            "/etc/hermes/astra/skills",
            "/etc/hermes/dubble/skills",
            "/etc/hermes/rigel/skills",
        )
        for name in normal_playbooks:
            text = (ROOT / "playbooks" / "agents" / name).read_text(
                encoding="utf-8"
            )
            for value in forbidden:
                with self.subTest(playbook=name, forbidden=value):
                    self.assertNotIn(value, text)

    def test_unknown_path_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "sample.yml"
            source.write_text(
                '- name: Unknown\n  ansible.builtin.file:\n'
                '    path: /var/lib/unreviewed-hermes-state\n',
                encoding="utf-8",
            )
            contract = json.loads(json.dumps(self.contract))
            contract["scope"]["sourceGlobs"] = ["sample.yml"]
            with self.assertRaisesRegex(
                MODULE.OwnershipAuditError, "unclassified-path-reference"
            ):
                MODULE.audit(root, contract)

    def test_contract_rejects_duplicate_prefixes(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "contract.json"
            contract = json.loads(json.dumps(self.contract))
            contract["rules"].append(dict(contract["rules"][0], id="duplicate"))
            path.write_text(json.dumps(contract), encoding="utf-8")
            with self.assertRaisesRegex(
                MODULE.OwnershipAuditError, "contract-rule-identity"
            ):
                MODULE.load_contract(path)

    def test_forbidden_docker_socket_is_explicit(self):
        rule = MODULE.classify("/var/run/docker.sock", self.contract["rules"])
        self.assertIsNotNone(rule)
        self.assertEqual(rule["classification"], "forbidden-interface")
        self.assertEqual(
            rule["normalConvergence"], "must-remain-unavailable-to-agents"
        )

    def test_disposable_systemd_init_is_external_distribution_state(self):
        rule = MODULE.classify("/sbin/init", self.contract["rules"])
        self.assertIsNotNone(rule)
        self.assertEqual(rule["classification"], "external-readonly")
        self.assertEqual(rule["owner"], "distribution")


if __name__ == "__main__":
    unittest.main()
