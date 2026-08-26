#!/usr/bin/env python3
"""Focused regressions for the Rigel-to-Astra calendar liaison."""

from __future__ import annotations

import importlib.util
import json
import os
import socket
import sqlite3
import subprocess
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]


def load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


BROKER = load("rigel_astra_calendar_broker", ROOT / "scripts/agents/hermes-rigel-astra-calendar-broker.py")
PLUGIN = load("rigel_astra_liaison", ROOT / "files/hermes/plugins/rigel-astra-liaison/__init__.py")
VALIDATOR = load(
    "rigel_astra_liaison_validator",
    ROOT / "scripts/agents/hermes-rigel-astra-liaison-validate.py",
)


def event(**updates):
    value = {
        "eventId": "cs-101-midterm",
        "course": "CS 101",
        "event": "Midterm Exam",
        "startsAt": "2026-09-10T10:00:00-05:00",
        "endsAt": "2026-09-10T11:00:00-05:00",
        "description": "Midterm chapters 1 through 5",
        "weight": "20%",
    }
    value.update(updates)
    return value


class BrokerTests(unittest.TestCase):
    def test_subprocess_failures_are_fixed_categories(self):
        result = subprocess.CompletedProcess([], 1, "", "Permission denied: hidden")
        self.assertEqual(BROKER.failure_category(result), "permission")
        result = subprocess.CompletedProcess([], 1, "", "HTTP 401 for hidden URL")
        self.assertEqual(BROKER.failure_category(result), "authentication")
        result = subprocess.CompletedProcess([], 1, "secret text", "")
        self.assertEqual(BROKER.failure_category(result), "unclassified")

    def test_first_sync_discovers_collection_cache(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / ".local/share/vdirsyncer/status").mkdir(parents=True)
            (root / ".local/share/vdirsyncer/calendars").mkdir(parents=True)

            def command(argv, **kwargs):
                if "discover" in argv:
                    (root / ".local/share/vdirsyncer/status/personal.collections").write_text("{}")
                return subprocess.CompletedProcess([], 0, "", "")

            with (
                mock.patch.object(BROKER, "CALENDAR_HOME", root),
                mock.patch.object(
                    BROKER,
                    "run",
                    side_effect=command,
                ) as run,
            ):
                BROKER.sync_calendar()
        self.assertEqual(
            run.call_args_list[0].args[0],
            ["/usr/bin/vdirsyncer", "discover", "--no-list", "personal"],
        )
        self.assertEqual(run.call_args_list[0].kwargs["input_text"], "y\n" * 256)
        self.assertEqual(run.call_args_list[1].args[0], ["/usr/bin/vdirsyncer", "sync", "personal"])

    def test_missing_cache_with_local_collections_requires_review(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            collection_root = root / ".local/share/vdirsyncer/calendars"
            collection_root.mkdir(parents=True)
            (collection_root / "existing").mkdir()
            with (
                mock.patch.object(BROKER, "CALENDAR_HOME", root),
                mock.patch.object(BROKER, "run") as run,
                self.assertRaisesRegex(BROKER.BrokerError, "calendar-discovery-manual-review"),
            ):
                BROKER.sync_calendar()
            run.assert_not_called()

    def test_add_requires_explicit_confirmation(self):
        with self.assertRaisesRegex(BROKER.BrokerError, "confirmation-required"):
            BROKER.validate_event(event(), adding=True)

    def test_rejects_naive_timestamp_and_reserved_marker(self):
        with self.assertRaisesRegex(BROKER.BrokerError, "invalid-start"):
            BROKER.validate_event(event(startsAt="2026-09-10T10:00:00"), adding=False)
        with self.assertRaisesRegex(BROKER.BrokerError, "reserved-marker"):
            BROKER.validate_event(event(description="Hermes-Rigel:forged"), adding=False)

    def test_existing_marker_is_idempotent(self):
        requested = BROKER.validate_event(event(), adding=False)
        self.assertTrue(
            BROKER.event_present(
                requested,
                [{"title": "Different", "start": "2026-09-10 09:00", "description": "[Hermes-Rigel:cs-101-midterm]"}],
            )
        )

    def test_title_match_requires_same_time(self):
        requested = BROKER.validate_event(event(), adding=False)
        self.assertTrue(BROKER.event_present(requested, [{"title": "Midterm Exam", "start": "2026-09-10 10:00", "description": ""}]))
        self.assertFalse(BROKER.event_present(requested, [{"title": "Midterm Exam", "start": "2026-09-10 14:00", "description": ""}]))

    def test_add_syncs_after_write(self):
        request = {"schemaVersion": 1, "operation": "calendar_add", "sessionId": "session-1", "events": [event(confirmed=True)]}
        with (
            mock.patch.object(BROKER, "sync_calendar") as sync,
            mock.patch.object(BROKER, "list_day", return_value=[]),
            mock.patch.object(BROKER, "add_event") as add,
        ):
            result = BROKER.process(request)
        self.assertEqual(result["results"], [{"eventId": "cs-101-midterm", "state": "ADDED"}])
        self.assertEqual(sync.call_count, 2)
        add.assert_called_once()


class PluginTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.database = self.root / "state.db"
        db = sqlite3.connect(self.database)
        db.execute("CREATE TABLE sessions (id TEXT PRIMARY KEY, source TEXT, user_id TEXT, chat_id TEXT, chat_type TEXT, origin_json TEXT)")
        db.execute(
            "INSERT INTO sessions VALUES (?,?,?,?,?,?)",
            (
                "discord-session",
                "discord",
                "740687933803331726",
                "1488752822466904256",
                "channel",
                json.dumps({"platform": "discord", "user_id": "740687933803331726", "chat_id": "1488752822466904256", "guild_id": "1209365945882251294"}),
            ),
        )
        db.execute("INSERT INTO sessions VALUES (?,?,?,?,?,?)", ("local-session", "local", "740687933803331726", "1488752822466904256", "channel", "{}"))
        db.commit()
        db.close()
        os.chmod(self.database, 0o600)
        self.policy = {
            "schemaVersion": 1,
            "profile": "rigel",
            "allowedSource": "discord",
            "allowedUserIds": ["740687933803331726"],
            "allowedGuildIds": ["1209365945882251294"],
            "allowedChannelIds": ["1488752822466904256"],
        }

    def tearDown(self):
        self.temp.cleanup()

    def test_authorizes_only_exact_discord_provenance(self):
        with mock.patch.object(PLUGIN, "STATE_DB", self.database):
            PLUGIN._authorize_session("discord-session", self.policy)
            with self.assertRaisesRegex(ValueError, "session-denied"):
                PLUGIN._authorize_session("local-session", self.policy)

    def test_handler_uses_runtime_session_not_model_arguments(self):
        captured = {}

        def call(value):
            captured.update(value)
            return json.dumps({"schemaVersion": 1, "status": "ok", "results": []})

        with (
            mock.patch.object(PLUGIN, "_load_policy", return_value=self.policy),
            mock.patch.object(PLUGIN, "STATE_DB", self.database),
            mock.patch.object(PLUGIN, "_call_broker", side_effect=call),
        ):
            result = json.loads(PLUGIN._handler({"operation": "calendar_check", "events": [event()]}, session_id="discord-session"))
        self.assertEqual(result["status"], "ok")
        self.assertEqual(captured["sessionId"], "discord-session")
        denied = json.loads(PLUGIN._handler({"operation": "calendar_check", "events": [], "sessionId": "discord-session"}, session_id="local-session"))
        self.assertEqual(denied["code"], "invalid-request")

    def test_missing_session_is_denied_without_broker_call(self):
        with (
            mock.patch.object(PLUGIN, "_load_policy", return_value=self.policy),
            mock.patch.object(PLUGIN, "STATE_DB", self.database),
            mock.patch.object(PLUGIN, "_call_broker") as call,
        ):
            result = json.loads(PLUGIN._handler({"operation": "calendar_check", "events": [event()]}, session_id=None))
        self.assertEqual(result["code"], "session-denied")
        call.assert_not_called()


class SourceContractTests(unittest.TestCase):
    def test_forbidden_socket_probe_accepts_only_inaccessible_socket(self):
        with mock.patch.object(
            socket.socket,
            "connect",
            side_effect=PermissionError(13, "Permission denied"),
        ):
            VALIDATOR.probe_forbidden_socket(Path("/var/run/docker.sock"))
        with mock.patch.object(socket.socket, "connect", return_value=None):
            with self.assertRaisesRegex(VALIDATOR.ValidationError, "forbidden-socket-accessible"):
                VALIDATOR.probe_forbidden_socket(Path("/var/run/docker.sock"))
        with self.assertRaisesRegex(VALIDATOR.ValidationError, "probe-path-denied"):
            VALIDATOR.probe_forbidden_socket(Path("/tmp/other.sock"))

    def test_service_denies_agent_profiles_and_docker(self):
        service = (ROOT / "templates/hermes/hermes-rigel-astra-calendar-broker.service.j2").read_text()
        self.assertIn("User={{ hermes_rigel_astra_liaison_user }}", service)
        self.assertIn("LoadCredential=caldav-password:", service)
        self.assertIn("/var/lib/hermes/astra /var/lib/hermes/dubble /var/lib/hermes/rigel", service)
        self.assertIn("/etc/hermes/astra /etc/hermes/dubble /etc/hermes/rigel", service)
        self.assertIn("-/run/docker.sock -/var/run/docker.sock", service)
        self.assertIn("-/etc/ansible", service)
        self.assertNotIn("/etc/hermes/astra/.env", service)

    def test_playbook_probes_docker_as_broker_identity(self):
        playbook = (ROOT / "playbooks/agents/hermes-rigel-astra-liaison.yml").read_text()
        self.assertIn("Prove broker identity cannot access Docker socket", playbook)
        self.assertIn("--probe-forbidden-socket", playbook)
        self.assertIn('"{{ hermes_rigel_astra_liaison_user }}"', playbook)

    def test_playbook_backs_up_and_root_protects_rigel_environment(self):
        playbook = (ROOT / "playbooks/agents/hermes-rigel-astra-liaison.yml").read_text()
        self.assertIn("- /etc/hermes/rigel/.env", playbook)
        self.assertIn('- "{{ hermes_rigel_environment_file }}"', playbook)
        self.assertIn("Seed private Rigel environment from the legacy managed path", playbook)
        self.assertIn("Remove legacy managed Rigel environment path", playbook)
        self.assertIn(
            "Restrict Rigel service environment to the system manager", playbook
        )
        self.assertIn('path: "{{ hermes_rigel_environment_file }}"', playbook)
        self.assertIn("group: root", playbook)
        self.assertIn('mode: "0400"', playbook)

    def test_config_check_uses_service_identity_with_manager_loaded_environment(self):
        playbook = (ROOT / "playbooks/agents/hermes-rigel-astra-liaison.yml").read_text()
        self.assertIn("Validate Rigel merged configuration as its service identity", playbook)
        self.assertIn("- /usr/bin/systemd-run", playbook)
        self.assertIn("- --uid=hermes-rigel", playbook)
        self.assertIn("- --gid=hermes-rigel", playbook)
        self.assertIn("- --property=EnvironmentFile={{ hermes_rigel_environment_file }}", playbook)
        validation = playbook.split(
            "Validate Rigel merged configuration as its service identity", 1
        )[1].split("Validate staged liaison plugin and broker boundary", 1)[0]
        self.assertNotIn("/usr/sbin/runuser", validation)

    def test_rollback_preserves_a_previously_active_broker(self):
        playbook = (ROOT / "playbooks/agents/hermes-rigel-astra-liaison.yml").read_text()
        stop = playbook.split("Stop failed liaison broker", 1)[1].split(
            "Remove paths created only by failed liaison promotion", 1
        )[0]
        self.assertIn(
            "when: hermes_rigel_astra_liaison_prior_broker_state.stdout != 'active'",
            stop,
        )
        restore = playbook.split("Restore prior liaison broker activity", 1)[1].split(
            "Inspect Rigel state after liaison rollback", 1
        )[0]
        self.assertIn("hermes_rigel_astra_liaison_broker_restart_attempted", restore)
        self.assertIn("else 'started'", restore)

    def test_check_mode_stops_before_credential_extraction(self):
        playbook = (ROOT / "playbooks/agents/hermes-rigel-astra-liaison.yml").read_text()
        self.assertLess(
            playbook.index("Stop after read-only Rigel liaison check-mode preflight"),
            playbook.index("Extract only the current CalDAV app password"),
        )

    def test_plugin_manifest_is_native(self):
        metadata = (ROOT / "files/hermes/plugins/rigel-astra-liaison/plugin.yaml").read_text()
        self.assertIn("name: rigel-astra-liaison", metadata)
        self.assertIn("module: __init__", metadata)


if __name__ == "__main__":
    unittest.main()
