#!/usr/bin/env python3
"""Structural tests for native non-root Astra remote access."""

from __future__ import annotations

import unittest
from pathlib import Path

import yaml


ROOT = Path(__file__).parents[2]


class HermesRemoteAccessTests(unittest.TestCase):
    def test_playbook_uses_dedicated_identity_and_no_sudo(self):
        text = (ROOT / "playbooks/agents/hermes-remote-access.yml").read_text()
        for required in (
            "Require exact Hermes remote access authorization",
            "Generate Astra non-root SSH identity",
            "Create controller-side Astra access rollback directory",
            "Preserve prior local Astra access files",
            "Create targeted Astra remote access rollback directory",
            "Preserve prior Astra remote authorized key",
            "Create dedicated non-root Astra account",
            "Install the single Astra public key",
            "Remove any Astra sudo policy",
            "Require only Astra and read-only operational groups",
            "Mark reachable host Astra access as provisioned",
            "Require every critical Astra collector host",
            "End currently unreachable remote hosts without hiding coverage",
            "Verify each managed Linux host as Astra",
            "Record complete native Astra remote access coverage",
        ):
            self.assertIn(required, text)
        self.assertIn("systemd-journal", text)
        self.assertIn("adm", text)
        self.assertIn("password_lock: true", text)
        self.assertNotIn("NOPASSWD", text)
        self.assertNotIn("docker.sock", text)
        self.assertIn("ignore_unreachable: true", text)

    def test_critical_hosts_and_partial_state_are_explicit(self):
        variables = yaml.safe_load(
            (ROOT / "inventory/group_vars/hermes_hosts/vars.yml").read_text()
        )
        self.assertEqual(
            variables["hermes_remote_access_required_hosts"],
            ["ts440", "docker-vm", "media-vm", "mercury"],
        )
        self.assertEqual(
            variables["hermes_remote_access_state_live"],
            "/var/lib/hermes/astra/state/remote-access.json",
        )
        heartbeat = (
            ROOT
            / "files/hermes/profile-skills/astra/operational-heartbeat/SKILL.md"
        ).read_text()
        normalized_heartbeat = " ".join(heartbeat.split())
        self.assertIn(
            "Remote-access SSH mode is intentionally disabled",
            normalized_heartbeat,
        )
        self.assertIn(
            "do not read or require `state/remote-access.json`",
            normalized_heartbeat,
        )
        self.assertIn("Never fall back", normalized_heartbeat)

    def test_ssh_client_is_fail_closed(self):
        text = (ROOT / "templates/hermes/astra-ssh-config.j2").read_text()
        self.assertIn("User hermes-astra", text)
        self.assertIn("BatchMode yes", text)
        self.assertIn("StrictHostKeyChecking yes", text)
        self.assertIn("IdentitiesOnly yes", text)
        self.assertNotIn("StrictHostKeyChecking no", text)


if __name__ == "__main__":
    unittest.main()
