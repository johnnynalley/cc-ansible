#!/usr/bin/env python3

from __future__ import annotations

import argparse
import importlib.util
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

MODULE_PATH = Path(__file__).with_name("openclaw-doctor-rehearsal.py")
PLAYBOOK_PATH = (
    Path(__file__).parents[2] / "playbooks/agents/openclaw-doctor-rehearsal.yml"
)
SPEC = importlib.util.spec_from_file_location("openclaw_doctor_rehearsal", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE)


class DoctorRehearsalTests(unittest.TestCase):
    def test_playbook_builds_agent_paths_without_capture_replacements(self) -> None:
        playbook = PLAYBOOK_PATH.read_text(encoding="utf-8")
        self.assertNotIn(r"\\1", playbook)
        self.assertIn("Add per-agent OpenClaw Doctor source paths", playbook)
        self.assertIn(
            "Create per-agent OpenClaw Doctor database destinations", playbook
        )
        self.assertIn("Create OpenClaw Doctor generation directories", playbook)
        self.assertIn(
            "Create private OpenClaw Doctor generation content directories",
            playbook,
        )
        self.assertIn(
            '"OPENCLAW_STATE_DIR={{ openclaw_doctor_rehearsal_generation_state }}"',
            playbook,
        )
        self.assertNotIn(
            '"OPENCLAW_STATE_DIR={{ openclaw_doctor_rehearsal_generation_state }}/state"',
            playbook,
        )
        self.assertIn("--property=ProtectHome=tmpfs", playbook)
        self.assertNotIn("--property=ProtectHome=yes", playbook)
        self.assertNotIn("--property=InaccessiblePaths=/home/johnny", playbook)

    def test_transform_rewrites_paths_and_removes_secret_values(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            source_state = root / "source-state"
            source_workspace = source_state / "workspace"
            target_state = root / "target-state"
            target_workspace = target_state / "workspace"
            codex_path = root / "runtime" / "codex"
            discord_path = root / "runtime" / "discord"
            source_workspace.mkdir(parents=True)
            target_workspace.mkdir(parents=True)
            codex_path.mkdir(parents=True)
            discord_path.mkdir(parents=True)
            (codex_path / "openclaw.plugin.json").write_text("{}\n")
            (discord_path / "openclaw.plugin.json").write_text("{}\n")
            source = root / "source.json"
            output = root / "target.json"
            report = root / "report.json"
            source.write_text(
                json.dumps(
                    {
                        "env": {"OPENROUTER_API_KEY": "forbidden-env-secret"},
                        "gateway": {
                            "mode": "local",
                            "bind": "tailnet",
                            "port": 18789,
                            "auth": {
                                "mode": "token",
                                "token": {"source": "env", "id": "GATEWAY_TOKEN"},
                            },
                        },
                        "channels": {
                            "discord": {
                                "enabled": True,
                                "token": "forbidden-channel-secret",
                            }
                        },
                        "agents": {
                            "list": [
                                {
                                    "id": "main",
                                    "workspace": str(source_workspace / "main"),
                                }
                            ]
                        },
                        "plugins": {
                            "allow": ["codex", "nextcloud-talk", "openai"],
                            "entries": {
                                "openclaw-mem0": {
                                    "config": {"apiKey": "forbidden-plugin-secret"}
                                },
                                "nextcloud-talk": {"enabled": True},
                            },
                        },
                    }
                ),
                encoding="utf-8",
            )

            result = MODULE.transform_config(
                argparse.Namespace(
                    source=str(source),
                    output=str(output),
                    report=str(report),
                    source_state_root=str(source_state),
                    source_workspace_root=str(source_workspace),
                    target_state_root=str(target_state),
                    target_workspace_root=str(target_workspace),
                    plugin_path=[
                        f"codex={codex_path}",
                        f"discord={discord_path}",
                    ],
                    retire_plugin=["nextcloud-talk"],
                    gateway_port=19789,
                    forbidden_literal=[
                        "forbidden-env-secret",
                        "forbidden-channel-secret",
                        "forbidden-plugin-secret",
                    ],
                )
            )

            transformed = json.loads(output.read_text(encoding="utf-8"))
            serialized = json.dumps(transformed)
            self.assertEqual(transformed["env"], {})
            self.assertEqual(transformed["gateway"]["bind"], "loopback")
            self.assertEqual(transformed["gateway"]["port"], 19789)
            self.assertEqual(transformed["gateway"]["auth"]["token"], MODULE.REDACTED)
            self.assertFalse(transformed["channels"]["discord"]["enabled"])
            self.assertEqual(
                transformed["agents"]["list"][0]["workspace"],
                str(target_workspace / "main"),
            )
            self.assertEqual(
                transformed["plugins"]["load"]["paths"],
                [str(codex_path), str(discord_path)],
            )
            self.assertEqual(
                transformed["plugins"]["allow"], ["codex", "openai", "discord"]
            )
            self.assertNotIn("nextcloud-talk", transformed["plugins"]["entries"])
            self.assertNotIn("forbidden", serialized)
            self.assertEqual(result["status"], "ok")
            self.assertEqual(result["managedPlugins"], ["codex", "discord"])
            self.assertEqual(result["retiredPlugins"], ["nextcloud-talk"])
            self.assertTrue(report.exists())

    def test_transform_rejects_embedded_source_reference(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            source_state = root / "source"
            source_workspace = source_state / "workspace"
            target_state = root / "target"
            target_workspace = target_state / "workspace"
            codex_path = root / "codex"
            for path in (source_workspace, target_workspace, codex_path):
                path.mkdir(parents=True)
            (codex_path / "openclaw.plugin.json").write_text("{}\n")
            source = root / "source.json"
            source.write_text(
                json.dumps({"meta": {"note": f"uses {source_state}/secret"}}),
                encoding="utf-8",
            )

            with self.assertRaises(MODULE.RehearsalError):
                MODULE.transform_config(
                    argparse.Namespace(
                        source=str(source),
                        output=str(root / "output.json"),
                        report=None,
                        source_state_root=str(source_state),
                        source_workspace_root=str(source_workspace),
                        target_state_root=str(target_state),
                        target_workspace_root=str(target_workspace),
                        plugin_path=[f"codex={codex_path}"],
                        retire_plugin=[],
                        gateway_port=19789,
                        forbidden_literal=[],
                    )
                )

    def test_transform_rejects_retired_plugin_slot(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            source_state = root / "source"
            source_workspace = source_state / "workspace"
            target_state = root / "target"
            target_workspace = target_state / "workspace"
            codex_path = root / "codex"
            for path in (source_workspace, target_workspace, codex_path):
                path.mkdir(parents=True)
            (codex_path / "openclaw.plugin.json").write_text("{}\n")
            source = root / "source.json"
            source.write_text(
                json.dumps(
                    {
                        "plugins": {
                            "allow": ["codex", "retired-memory"],
                            "slots": {"memory": "retired-memory"},
                        }
                    }
                ),
                encoding="utf-8",
            )

            with self.assertRaises(MODULE.RehearsalError):
                MODULE.transform_config(
                    argparse.Namespace(
                        source=str(source),
                        output=str(root / "output.json"),
                        report=None,
                        source_state_root=str(source_state),
                        source_workspace_root=str(source_workspace),
                        target_state_root=str(target_state),
                        target_workspace_root=str(target_workspace),
                        plugin_path=[f"codex={codex_path}"],
                        retire_plugin=["retired-memory"],
                        gateway_port=19789,
                        forbidden_literal=[],
                    )
                )

    def test_sqlite_backup_scrubs_only_agent_auth(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            source = root / "source.sqlite"
            target = root / "target.sqlite"
            report = root / "backup.json"
            connection = sqlite3.connect(source)
            connection.executescript("""
                CREATE TABLE auth_profile_state (id TEXT PRIMARY KEY, value TEXT);
                CREATE TABLE auth_profile_store (id TEXT PRIMARY KEY, value TEXT);
                CREATE TABLE memory_index_state (id TEXT PRIMARY KEY, value TEXT);
                INSERT INTO auth_profile_state VALUES ('one', 'secret-a');
                INSERT INTO auth_profile_store VALUES ('one', 'secret-b');
                INSERT INTO memory_index_state VALUES ('one', 'retained');
                """)
            connection.commit()
            connection.close()

            result = MODULE.sqlite_backup(
                argparse.Namespace(
                    source=str(source),
                    target=str(target),
                    output=str(report),
                    scrub_agent_auth=True,
                )
            )

            source_connection = sqlite3.connect(source)
            target_connection = sqlite3.connect(target)
            try:
                self.assertEqual(
                    source_connection.execute(
                        "SELECT COUNT(*) FROM auth_profile_store"
                    ).fetchone()[0],
                    1,
                )
                self.assertEqual(
                    target_connection.execute(
                        "SELECT COUNT(*) FROM auth_profile_store"
                    ).fetchone()[0],
                    0,
                )
                self.assertEqual(
                    target_connection.execute(
                        "SELECT value FROM memory_index_state"
                    ).fetchone()[0],
                    "retained",
                )
            finally:
                source_connection.close()
                target_connection.close()
            self.assertEqual(result["quickCheck"], "ok")
            self.assertTrue(result["scrubbedAgentAuth"])

    def test_manifest_and_diff_report_content_changes(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            tree = root / "tree"
            tree.mkdir()
            payload = tree / "payload.txt"
            payload.write_text("before\n", encoding="utf-8")
            before = root / "before.json"
            after = root / "after.json"
            diff = root / "diff.json"
            MODULE.manifest_tree(
                argparse.Namespace(root=str(tree), output=str(before), exclude=[])
            )
            payload.write_text("after\n", encoding="utf-8")
            (tree / "added.txt").write_text("new\n", encoding="utf-8")
            MODULE.manifest_tree(
                argparse.Namespace(root=str(tree), output=str(after), exclude=[])
            )
            result = MODULE.diff_manifests(
                argparse.Namespace(
                    before=str(before), after=str(after), output=str(diff)
                )
            )
            self.assertEqual(result["added"], ["added.txt"])
            self.assertEqual(result["modified"], ["payload.txt"])
            self.assertEqual(result["removed"], [])

    def test_manifest_rejects_symlink(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            tree = root / "tree"
            tree.mkdir()
            (tree / "payload.txt").write_text("payload\n", encoding="utf-8")
            (tree / "link.txt").symlink_to(tree / "payload.txt")
            with self.assertRaises(MODULE.RehearsalError):
                MODULE.manifest_tree(
                    argparse.Namespace(
                        root=str(tree), output=str(root / "manifest.json"), exclude=[]
                    )
                )

    def test_sqlite_summary_contains_digests_not_values(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            database = root / "state.sqlite"
            output = root / "summary.json"
            connection = sqlite3.connect(database)
            connection.execute(
                "CREATE TABLE state (id INTEGER PRIMARY KEY, value TEXT)"
            )
            connection.execute("INSERT INTO state(value) VALUES (?)", ("private",))
            connection.commit()
            connection.close()

            result = MODULE.sqlite_summary(
                argparse.Namespace(
                    database=str(database), output=str(output), exclude_table=[]
                )
            )
            serialized = output.read_text(encoding="utf-8")
            self.assertEqual(result["tables"]["state"]["rowCount"], 1)
            self.assertNotIn("private", serialized)

            excluded = MODULE.sqlite_summary(
                argparse.Namespace(
                    database=str(database),
                    output=str(root / "excluded.json"),
                    exclude_table=["state"],
                )
            )
            self.assertEqual(excluded["excludedTables"], ["state"])
            self.assertEqual(excluded["tables"], {})

            with self.assertRaises(MODULE.RehearsalError):
                MODULE.sqlite_summary(
                    argparse.Namespace(
                        database=str(database),
                        output=str(root / "unknown.json"),
                        exclude_table=["missing"],
                    )
                )


if __name__ == "__main__":
    unittest.main()
