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
SNAPSHOT_TASK_PATH = Path(__file__).parents[2] / "tasks/openclaw-doctor-snapshot.yml"
PLUGIN_SOURCE_TASK_PATH = (
    Path(__file__).parents[2] / "tasks/openclaw-doctor-plugin-source.yml"
)
SPEC = importlib.util.spec_from_file_location("openclaw_doctor_rehearsal", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE)


class DoctorRehearsalTests(unittest.TestCase):
    @staticmethod
    def gateway_secret_file(root: Path) -> str:
        secret_file = root / "secrets.json"
        secret_file.write_text(
            '{"gateway":{"token":"unit-test-token-with-more-than-32-bytes"}}\n',
            encoding="utf-8",
        )
        secret_file.chmod(0o400)
        return str(secret_file)

    def test_playbook_builds_agent_paths_without_capture_replacements(self) -> None:
        playbook = PLAYBOOK_PATH.read_text(encoding="utf-8")
        snapshot_tasks = SNAPSHOT_TASK_PATH.read_text(encoding="utf-8")
        plugin_source_tasks = PLUGIN_SOURCE_TASK_PATH.read_text(encoding="utf-8")
        doctor_sources = playbook + plugin_source_tasks
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
        self.assertIn("--property=RuntimeMaxSec=300s", playbook)
        self.assertIn("NPM_CONFIG_OFFLINE=true", playbook)
        self.assertIn("NPM_CONFIG_FETCH_RETRIES=0", playbook)
        self.assertIn("sqlite-checkpoint", snapshot_tasks)
        self.assertIn("plugins', 'install'", playbook)
        self.assertEqual(playbook.count("'plugins', 'inspect'"), 3)
        self.assertNotIn("'--link'", playbook)
        self.assertNotIn("--install-records-source", playbook)
        self.assertNotIn(
            "openclaw_doctor_rehearsal_runtime }}/plugins/", doctor_sources
        )
        self.assertIn(
            "openclaw_isolated_gateway_plugin_state_root == '/var/lib/openclaw-isolated/state/npm'",
            playbook,
        )
        self.assertIn(
            "Find direct native managed plugin package roots", plugin_source_tasks
        )
        self.assertIn("depth: 2", plugin_source_tasks)
        self.assertIn(
            "Require immutable direct native managed plugin project directories",
            plugin_source_tasks,
        )
        self.assertIn(
            "Require exact native managed plugin source identities",
            plugin_source_tasks,
        )
        self.assertIn("plugin-source-evidence.json", playbook)
        self.assertIn("openclaw-rehearsal-retention.py", playbook)
        self.assertIn("state-retention-plan.json", playbook)
        self.assertIn("doctor-retention-plan.json", playbook)
        self.assertIn("doctor-retention-post-plan.json", playbook)
        self.assertIn("doctor-retention-post-result.json", playbook)
        self.assertIn("--suspend-managed-plugin-slots", playbook)
        self.assertIn("--gateway-secret-file", playbook)
        self.assertIn("fresh OpenClaw Doctor rehearsal Gateway secret", playbook)
        self.assertIn("Preserve OpenClaw Doctor lint JSON", playbook)
        self.assertIn("Preserve OpenClaw Doctor lint diagnostics", playbook)
        self.assertIn("doctor-lint.stderr.txt", playbook)
        self.assertNotIn(
            "{{ openclaw_doctor_rehearsal_lint.stdout }}\n"
            "          {{ openclaw_doctor_rehearsal_lint.stderr }}",
            playbook,
        )
        self.assertIn(
            "(openclaw_doctor_rehearsal_lint.stdout | from_json).ok | bool",
            playbook,
        )
        self.assertIn(
            "(openclaw_doctor_rehearsal_lint.stdout | from_json).findings | length == 0",
            playbook,
        )
        secret_restore = playbook.index(
            "- name: Restore owner-only OpenClaw Doctor Gateway secret permissions"
        )
        final_config = playbook.index(
            "- name: Restore sanitized retained OpenClaw plugin configuration"
        )
        self.assertLess(secret_restore, final_config)
        self.assertIn("ownershipRecordSource': 'npm'", playbook)
        self.assertIn("openKeyedStore is only available for trusted plugins", playbook)
        legacy_inspect = playbook.index(
            "- name: Inspect copied OpenClaw plugin install records"
        )
        legacy_uninstall = playbook.index(
            "- name: Retire copied legacy OpenClaw plugin install records"
        )
        supported_install = playbook.index(
            "- name: Install exact managed plugins into copied modern state"
        )
        native_source_validation = playbook.index(
            "- name: Validate frozen native plugin source before rehearsal mutation"
        )
        check_mode_stop = playbook.index(
            "- name: Stop OpenClaw Doctor rehearsal before mutation in check mode"
        )
        plugin_freeze = playbook.index(
            "- name: Freeze npm-managed plugin code before Doctor"
        )
        state_retention = playbook.index(
            "- name: Apply bounded upstream state rehearsal generation retention"
        )
        doctor_retention = playbook.index(
            "- name: Apply bounded OpenClaw Doctor generation retention"
        )
        generation_allocation = playbook.index(
            "- name: Create OpenClaw Doctor generation directories"
        )
        capacity_gate = playbook.index(
            "- name: Require one capacious OpenClaw Doctor destination filesystem"
        )
        promotion = playbook.index(
            "- name: Record successful OpenClaw Doctor rehearsal promotion"
        )
        post_retention = playbook.index(
            "- name: Apply bounded post-promotion OpenClaw Doctor generation retention"
        )
        self.assertLess(legacy_inspect, legacy_uninstall)
        self.assertLess(native_source_validation, check_mode_stop)
        self.assertLess(native_source_validation, supported_install)
        self.assertLess(native_source_validation, state_retention)
        self.assertLess(state_retention, doctor_retention)
        self.assertLess(doctor_retention, generation_allocation)
        self.assertLess(generation_allocation, capacity_gate)
        self.assertLess(promotion, post_retention)
        self.assertLess(legacy_uninstall, supported_install)
        self.assertLess(supported_install, final_config)
        self.assertLess(final_config, plugin_freeze)
        trust_assertions = [
            line for line in playbook.splitlines() if "trustedOfficialInstall" in line
        ]
        self.assertEqual(len(trust_assertions), 3)
        for assertion in trust_assertions:
            self.assertIn("inspections", assertion)
        for task_name in (
            "Assign writable OpenClaw Doctor generation to migration identity",
            "Freeze npm-managed plugin code before Doctor",
            "Freeze validated OpenClaw Doctor generation",
        ):
            task_start = playbook.index(f"- name: {task_name}")
            task_end = playbook.find("\n    - name:", task_start + 1)
            task = playbook[task_start:task_end]
            self.assertIn("recurse: true", task)
            self.assertIn("follow: false", task)
        self.assertIn(
            "Capture immutable OpenClaw runtime before rehearsal mutation", playbook
        )
        self.assertIn(
            "Capture immutable OpenClaw runtime after rehearsal mutation", playbook
        )
        self.assertIn(
            "Require rehearsal confinement to copied OpenClaw state", playbook
        )
        self.assertNotIn("existing_paths.results[1].stat.lnk_source", playbook)
        self.assertNotIn("existing_paths.results[2].stat.lnk_source", playbook)
        self.assertNotIn("existing_paths.results[3].stat.lnk_source", playbook)

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
                        "secrets": {
                            "providers": {
                                "legacy": {
                                    "source": "exec",
                                    "command": "/home/johnny/legacy-secret-provider",
                                }
                            }
                        },
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
                            "defaults": {
                                "memorySearch": {
                                    "enabled": True,
                                    "provider": "gemini",
                                }
                            },
                            "list": [
                                {
                                    "id": "main",
                                    "workspace": str(source_workspace / "main"),
                                }
                            ],
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
                    managed_plugin=["codex", "discord"],
                    retire_plugin=["nextcloud-talk"],
                    disable_memory_search=True,
                    disable_plugin_runtime=["discord"],
                    gateway_port=19789,
                    gateway_secret_file=self.gateway_secret_file(root),
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
            self.assertEqual(transformed["gateway"]["auth"]["mode"], "token")
            self.assertEqual(
                transformed["gateway"]["auth"]["token"],
                {
                    "source": "file",
                    "provider": "doctor_rehearsal",
                    "id": "/gateway/token",
                },
            )
            self.assertFalse(transformed["gateway"]["auth"]["allowTailscale"])
            self.assertEqual(
                transformed["secrets"]["providers"]["doctor_rehearsal"]["path"],
                str(root / "secrets.json"),
            )
            self.assertNotIn("unit-test-token", serialized)
            self.assertNotIn("channels", transformed)
            self.assertEqual(
                transformed["agents"]["list"][0]["workspace"],
                str(target_workspace / "main"),
            )
            self.assertNotIn("load", transformed["plugins"])
            self.assertEqual(
                transformed["plugins"]["allow"], ["codex", "openai", "discord"]
            )
            self.assertNotIn("nextcloud-talk", transformed["plugins"]["entries"])
            self.assertFalse(transformed["plugins"]["entries"]["discord"]["enabled"])
            self.assertFalse(
                transformed["agents"]["defaults"]["memorySearch"]["enabled"]
            )
            self.assertNotIn("forbidden", serialized)
            self.assertEqual(result["status"], "ok")
            self.assertEqual(result["gatewayAuth"], "fresh-file-secretref")
            self.assertTrue(result["replacedSecretProviderConfig"])
            self.assertEqual(result["managedPlugins"], ["codex", "discord"])
            self.assertEqual(result["retiredPlugins"], ["nextcloud-talk"])
            self.assertEqual(result["disabledRuntimePlugins"], ["discord"])
            self.assertEqual(
                result["disabledMemorySearchPaths"],
                ["/agents/defaults/memorySearch"],
            )
            self.assertIn(
                "/plugins/entries/openclaw-mem0/config/apiKey",
                result["removedCredentialPaths"],
            )
            self.assertTrue(report.exists())

    def test_transform_suspends_only_managed_plugin_slots(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            source_state = root / "source"
            source_workspace = source_state / "workspace"
            target_state = root / "target"
            target_workspace = target_state / "workspace"
            for path in (source_workspace, target_workspace):
                path.mkdir(parents=True)
            source = root / "source.json"
            source.write_text(
                json.dumps(
                    {
                        "plugins": {
                            "allow": ["codex", "browser"],
                            "slots": {
                                "contextEngine": "codex",
                                "browser": "browser",
                            },
                        }
                    }
                ),
                encoding="utf-8",
            )

            output = root / "target.json"
            result = MODULE.transform_config(
                argparse.Namespace(
                    source=str(source),
                    output=str(output),
                    report=None,
                    source_state_root=str(source_state),
                    source_workspace_root=str(source_workspace),
                    target_state_root=str(target_state),
                    target_workspace_root=str(target_workspace),
                    managed_plugin=["codex"],
                    retire_plugin=[],
                    suspend_managed_plugin_slots=True,
                    gateway_port=19789,
                    gateway_secret_file=self.gateway_secret_file(root),
                    forbidden_literal=[],
                )
            )

            transformed = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(transformed["plugins"]["slots"], {"browser": "browser"})
            self.assertEqual(result["suspendedPluginSlots"], {"contextEngine": "codex"})

            final_output = root / "final.json"
            final_result = MODULE.transform_config(
                argparse.Namespace(
                    source=str(source),
                    output=str(final_output),
                    report=None,
                    source_state_root=str(source_state),
                    source_workspace_root=str(source_workspace),
                    target_state_root=str(target_state),
                    target_workspace_root=str(target_workspace),
                    managed_plugin=["codex"],
                    retire_plugin=[],
                    suspend_managed_plugin_slots=False,
                    gateway_port=19789,
                    gateway_secret_file=str(root / "secrets.json"),
                    forbidden_literal=[],
                )
            )
            final_transformed = json.loads(final_output.read_text(encoding="utf-8"))
            self.assertEqual(
                final_transformed["plugins"]["slots"],
                {"browser": "browser", "contextEngine": "codex"},
            )
            self.assertEqual(final_result["suspendedPluginSlots"], {})

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
                        managed_plugin=["codex"],
                        retire_plugin=[],
                        gateway_port=19789,
                        gateway_secret_file=self.gateway_secret_file(root),
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
                        managed_plugin=["codex"],
                        retire_plugin=["retired-memory"],
                        gateway_port=19789,
                        gateway_secret_file=self.gateway_secret_file(root),
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

    def test_manifest_records_root_and_entry_ownership(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            tree = root / "tree"
            tree.mkdir()
            payload = tree / "payload.txt"
            payload.write_text("payload\n", encoding="utf-8")

            result = MODULE.manifest_tree(
                argparse.Namespace(
                    root=str(tree), output=str(root / "manifest.json"), exclude=[]
                )
            )
            entries = {entry["relativePath"]: entry for entry in result["entries"]}
            self.assertEqual(entries["."]["uid"], tree.stat().st_uid)
            self.assertEqual(entries["."]["gid"], tree.stat().st_gid)
            self.assertEqual(entries["payload.txt"]["uid"], payload.stat().st_uid)
            self.assertEqual(entries["payload.txt"]["gid"], payload.stat().st_gid)

    def test_manifest_allows_only_reviewed_plugin_skill_symlinks(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            tree = root / "tree"
            plugin_root = root / "immutable-plugin"
            skill = plugin_root / "skills" / "discord"
            skill.mkdir(parents=True)
            (skill / "SKILL.md").write_text("# Discord\n", encoding="utf-8")
            links = tree / "plugin-skills"
            links.mkdir(parents=True)
            (links / "discord").symlink_to(skill, target_is_directory=True)

            result = MODULE.manifest_tree(
                argparse.Namespace(
                    root=str(tree),
                    output=str(root / "manifest.json"),
                    exclude=[],
                    allow_plugin_skill_target_root=[str(plugin_root)],
                )
            )
            symlink = next(
                entry for entry in result["entries"] if entry["type"] == "symlink"
            )
            self.assertEqual(symlink["relativePath"], "plugin-skills/discord")
            self.assertEqual(symlink["resolvedTarget"], str(skill))
            self.assertEqual(result["summary"]["symlinks"], 1)

            outside = root / "outside"
            outside.mkdir()
            (outside / "SKILL.md").write_text("# Outside\n", encoding="utf-8")
            (links / "discord").unlink()
            (links / "discord").symlink_to(outside, target_is_directory=True)
            with self.assertRaises(MODULE.RehearsalError):
                MODULE.manifest_tree(
                    argparse.Namespace(
                        root=str(tree),
                        output=str(root / "escaped.json"),
                        exclude=[],
                        allow_plugin_skill_target_root=[str(plugin_root)],
                    )
                )

    def test_manifest_allows_reviewed_npm_symlinks_only_in_dedicated_tree(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            tree = root / "npm"
            runtime = root / "runtime"
            package_bin = tree / "projects/plugin/node_modules/.bin"
            package_payload = tree / "projects/plugin/node_modules/tool/bin/tool.js"
            runtime_plugin = runtime / "openclaw"
            package_bin.mkdir(parents=True)
            package_payload.parent.mkdir(parents=True)
            runtime_plugin.mkdir(parents=True)
            package_payload.write_text("payload\n", encoding="utf-8")
            (package_bin / "tool").symlink_to(package_payload)
            (package_bin / "openclaw").symlink_to(
                runtime_plugin, target_is_directory=True
            )

            result = MODULE.manifest_tree(
                argparse.Namespace(
                    root=str(tree),
                    output=str(root / "npm.json"),
                    exclude=[],
                    allow_plugin_skill_target_root=[],
                    allow_symlink_target_root=[str(tree), str(runtime)],
                )
            )
            self.assertEqual(result["summary"]["symlinks"], 2)

            outside = root / "outside"
            outside.write_text("outside\n", encoding="utf-8")
            (package_bin / "tool").unlink()
            (package_bin / "tool").symlink_to(outside)
            with self.assertRaises(MODULE.RehearsalError):
                MODULE.manifest_tree(
                    argparse.Namespace(
                        root=str(tree),
                        output=str(root / "escaped-npm.json"),
                        exclude=[],
                        allow_plugin_skill_target_root=[],
                        allow_symlink_target_root=[str(tree), str(runtime)],
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
                    database=str(database),
                    output=str(output),
                    exclude_table=[],
                    ignore_column=[],
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
                    ignore_column=[],
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
                        ignore_column=[],
                    )
                )

    def test_sqlite_summary_normalizes_only_declared_columns(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            database = root / "state.sqlite"
            first = root / "first.json"
            second = root / "second.json"
            connection = sqlite3.connect(database)
            connection.execute(
                "CREATE TABLE schema_meta ("
                "meta_key TEXT PRIMARY KEY, role TEXT, updated_at INTEGER)"
            )
            connection.execute(
                "INSERT INTO schema_meta VALUES ('primary', 'global', 1)"
            )
            connection.commit()
            connection.close()

            first_result = MODULE.sqlite_summary(
                argparse.Namespace(
                    database=str(database),
                    output=str(first),
                    exclude_table=[],
                    ignore_column=["schema_meta.updated_at"],
                )
            )
            connection = sqlite3.connect(database)
            connection.execute(
                "UPDATE schema_meta SET updated_at = 2 WHERE meta_key = 'primary'"
            )
            connection.commit()
            connection.close()
            second_result = MODULE.sqlite_summary(
                argparse.Namespace(
                    database=str(database),
                    output=str(second),
                    exclude_table=[],
                    ignore_column=["schema_meta.updated_at"],
                )
            )

            self.assertEqual(first.read_bytes(), second.read_bytes())
            self.assertEqual(
                first_result["tables"]["schema_meta"]["ignoredColumns"],
                ["updated_at"],
            )
            self.assertEqual(first_result, second_result)

            with self.assertRaises(MODULE.RehearsalError):
                MODULE.sqlite_summary(
                    argparse.Namespace(
                        database=str(database),
                        output=str(root / "bad-column.json"),
                        exclude_table=[],
                        ignore_column=["schema_meta.missing"],
                    )
                )

    def test_sqlite_checkpoint_flushes_wal_and_preserves_committed_rows(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            database = root / "state.sqlite"
            report = root / "checkpoint.json"
            connection = sqlite3.connect(database)
            self.assertEqual(
                connection.execute("PRAGMA journal_mode=WAL").fetchone()[0], "wal"
            )
            connection.execute(
                "CREATE TABLE state (id INTEGER PRIMARY KEY, value TEXT)"
            )
            connection.execute("INSERT INTO state(value) VALUES ('retained')")
            connection.commit()
            connection.close()

            result = MODULE.sqlite_checkpoint(
                argparse.Namespace(database=str(database), output=str(report))
            )

            verification = sqlite3.connect(
                database.resolve().as_uri() + "?mode=ro&immutable=1", uri=True
            )
            try:
                self.assertEqual(
                    verification.execute("SELECT value FROM state").fetchone()[0],
                    "retained",
                )
            finally:
                verification.close()
            self.assertEqual(result["quickCheck"], "ok")
            self.assertEqual(result["checkpoint"]["busy"], 0)
            self.assertFalse(Path(f"{database}-wal").exists())
            self.assertFalse(Path(f"{database}-shm").exists())


if __name__ == "__main__":
    unittest.main()
