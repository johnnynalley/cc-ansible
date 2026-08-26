#!/usr/bin/env python3
"""Static and content-free regressions for the Rigel workflow smoke."""

from __future__ import annotations

import importlib.util
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock


ROOT = Path(__file__).parents[2]
SCRIPT = ROOT / "scripts/agents/hermes-rigel-workflow-smoke.py"
SCHEDULE = ROOT / "scripts/agents/hermes-rigel-schedule.py"


def load_module():
    spec = importlib.util.spec_from_file_location("rigel_workflow_smoke", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class RigelWorkflowSmokeTests(unittest.TestCase):
    def test_sandbox_hides_live_account_and_limits_tools(self) -> None:
        script = SCRIPT.read_text(encoding="utf-8")
        self.assertIn("--property=BindPaths={account}:{CANONICAL_ACCOUNT}", script)
        self.assertIn("--property=User={args.user}", script)
        self.assertIn("--property=NoNewPrivileges=yes", script)
        self.assertIn("--property=ProtectSystem=strict", script)
        self.assertIn("--property=ProtectHome=yes", script)
        self.assertIn("--property=CapabilityBoundingSet=", script)
        self.assertIn("--property=ReadWritePaths={CANONICAL_ACCOUNT}", script)
        self.assertIn('os.chown(temporary, account.pw_uid, account.pw_gid)', script)
        self.assertIn('"--toolsets",\n        "file,skills,todo"', script)
        self.assertIn('"--provider",\n        "openai-codex"', script)
        self.assertIn('TEST_MODEL = "gpt-5.6-sol"', script)
        self.assertIn('"--model",\n        TEST_MODEL', script)
        self.assertNotIn('"--ignore-user-config"', script)
        self.assertIn("verify_on_stop: false", script)
        self.assertIn("max_verify_nudges: 2", script)
        self.assertIn("todo_stop_guard: true", script)
        self.assertIn("max_todo_stop_nudges: 8", script)
        self.assertIn("create a native TodoStore checklist", script)
        self.assertIn("pending or in-progress todo", script)
        self.assertIn("Do not call skill_view", script)
        self.assertIn("Submit independent native", script)
        self.assertIn("plugins:\n  enabled: []", script)
        self.assertNotIn('"--reasoning"', script)
        self.assertNotIn("print(result.stdout", script)
        self.assertNotIn("print(result.stderr", script)
        self.assertIn("classify_agent_failure(result.stderr)", script)
        self.assertIn("run_tool_inventory_probe", script)
        self.assertIn("run_file_read_probe", script)
        self.assertIn("requiredFileToolsPresent", script)
        self.assertIn('f"PYTHONPATH={args.runtime_root}"', script)
        self.assertIn("require_managed_interpreter(args.hermes_python)", script)
        self.assertIn('raise SmokeError(f"scheduler-invalid:{code}")', script)
        self.assertIn('return f"bubblewrap-{reason}"', script)
        self.assertIn('("authentication", ("not authenticated"', script)
        self.assertIn("shutil.rmtree(temporary", script)
        self.assertIn('args.skills_root / "academic"', script)
        self.assertIn('profile / "skills/academic"', script)
        self.assertNotIn("managed_skills", script)
        self.assertNotIn('profile / "skills/managed/academic"', script)
        self.assertNotIn('/etc/hermes/rigel/skills', script)
        self.assertLess(
            script.index("workflow = validate_outputs"),
            script.index('agent["responseClassification"]["blockedClaim"]'),
        )
        self.assertIn("external delivery is outside scope", script)
        self.assertIn('"workflow": workflow', script)
        self.assertNotIn("liaison is intentionally unavailable", script)

    def test_content_free_output_validation_accepts_exact_scheduler_shape(self) -> None:
        module = load_module()
        with tempfile.TemporaryDirectory() as raw:
            account = Path(raw)
            courses = account / ".hermes/profiles/rigel/imported-data/courses"
            course = courses / module.COURSE_ID
            course.mkdir(parents=True)
            (course / "syllabus-raw.md").write_text("raw", encoding="utf-8")
            (course / "syllabus-context.md").write_text("context", encoding="utf-8")
            (courses / "semester-context.md").write_text(
                f"Active: {module.COURSE_ID}\n", encoding="utf-8"
            )
            events = []
            titles = {
                "midterm": "Midterm Assessment",
                "project": "Research Project Deadline",
                "final": "Comprehensive Final",
            }
            dates = {
                "midterm": "2026-09-15T10:00:00-05:00",
                "project": "2026-10-20T23:59:00-05:00",
                "final": "2026-12-10T10:00:00-06:00",
            }
            for index, category in enumerate(module.EXPECTED_EVENTS, 1):
                events.append(
                    {
                        "id": f"acceptance-{index}",
                        "course": module.COURSE_ID,
                        "title": titles[category],
                        "startsAt": dates[category],
                        "status": "scheduled",
                        "source": {"kind": "syllabus", "reference": "synthetic"},
                    }
                )
            state = {
                "schemaVersion": 1,
                "timezone": "America/Chicago",
                "semester": {
                    "id": "fall-2026",
                    "status": "active",
                    "startsOn": "2026-08-24",
                    "endsOn": "2026-12-15",
                },
                "events": events,
                "calendarRequests": [],
            }
            (courses / "academic-state.json").write_text(
                json.dumps(state), encoding="utf-8"
            )
            report = module.validate_outputs(account, SCHEDULE)
        self.assertTrue(report["schedulerSchemaValid"])
        self.assertEqual(report["events"], 3)

    def test_event_classifier_accepts_semantics_not_literal_titles(self) -> None:
        module = load_module()
        self.assertEqual(module.classify_synthetic_event("Midterm Assessment"), "midterm")
        self.assertEqual(module.classify_synthetic_event("Research Project Due"), "project")
        self.assertEqual(module.classify_synthetic_event("Comprehensive Final"), "final")
        self.assertIsNone(module.classify_synthetic_event("Weekly Homework"))

    def test_failure_classifier_is_bounded_and_specific(self) -> None:
        module = load_module()
        self.assertEqual(
            module.classify_agent_failure(
                b"bwrap: Can't chdir to /var/lib/hermes/rigel/example"
            ),
            "bubblewrap-chdir",
        )
        self.assertEqual(
            module.classify_agent_failure(b"bwrap: Creating new namespace failed"),
            "bubblewrap-namespace",
        )
        response = module.classify_agent_response(
            b"Unable to continue because write_file is not available."
        )
        self.assertTrue(response["blockedClaim"])
        self.assertTrue(response["mentionsWriteFile"])
        self.assertTrue(response["toolUnavailableClaim"])
        self.assertFalse(response["completionClaim"])
        self.assertEqual(
            module.synthetic_response_preview(b"Synthetic response."),
            "Synthetic response.",
        )
        self.assertEqual(
            module.classify_tool_error_category('{"error":"File does not exist"}'),
            "not-found",
        )
        self.assertEqual(
            module.classify_tool_error_category('{"error":"offset must be positive"}'),
            "pagination",
        )
        self.assertEqual(
            module.classify_synthetic_read_path(
                "courses/inbox/synthetic-syllabus.md"
            ),
            "syllabus-input",
        )
        self.assertEqual(
            module.classify_synthetic_read_path("../private"),
            "traversal",
        )

    def test_probe_mode_reuses_exact_sandbox_without_model_invocation(self) -> None:
        module = load_module()
        args = SimpleNamespace(
            systemd_run=Path("/usr/bin/systemd-run"),
            user="hermes-rigel",
            timeout=600,
        )
        with tempfile.TemporaryDirectory() as raw:
            account = Path(raw) / "disposable-account"
            imported = account / ".hermes/profiles/rigel/imported-data"
            imported.mkdir(parents=True)

            def complete_probe(*_args, **_kwargs):
                (imported / ".sandbox-write-probe").touch()
                return module.subprocess.CompletedProcess(
                    args=[], returncode=0, stdout=b"", stderr=b""
                )

            with mock.patch.object(
                module.subprocess, "run", side_effect=complete_probe
            ) as run:
                report = module.run_sandbox_probe(account, args)
        command = run.call_args.args[0]
        self.assertEqual(command[-2], "/usr/bin/touch")
        self.assertTrue(command[-1].endswith("/.sandbox-write-probe"))
        self.assertIn(
            "--property=BindPaths=" + str(account) + ":"
            + str(module.CANONICAL_ACCOUNT),
            command,
        )
        self.assertIn(
            "--property=WorkingDirectory="
            + str(module.CANONICAL_PROFILE / "imported-data"),
            command,
        )
        self.assertIn(
            "TERMINAL_CWD=" + str(module.CANONICAL_PROFILE / "imported-data"),
            command,
        )
        self.assertNotIn("openai-codex", command)
        self.assertNotIn(module.TEST_MODEL, command)
        self.assertFalse(report["modelInvoked"])
        self.assertTrue(report["mappedWriteVerified"])
        self.assertEqual(report["status"], "ready")
        self.assertEqual(report["sandboxSetup"], "systemd-private-account")

    def test_tool_probe_uses_runtime_registry_without_model_invocation(self) -> None:
        module = load_module()
        args = SimpleNamespace(
            systemd_run=Path("/usr/bin/systemd-run"),
            user="hermes-rigel",
            timeout=600,
            runtime_root=Path("/usr/local/lib/hermes-agent"),
            hermes_python=Path("/usr/local/lib/hermes-agent/venv/bin/python"),
        )
        payload = {
            "maxTodoStopNudges": 8,
            "todoStopGuard": True,
            "toolNames": sorted(module.REQUIRED_FILE_TOOLS | {"skill_view", "todo"}),
        }
        with tempfile.TemporaryDirectory() as raw:
            account = Path(raw) / "disposable-account"
            account.mkdir()
            with mock.patch.object(
                module.subprocess,
                "run",
                return_value=module.subprocess.CompletedProcess(
                    args=[],
                    returncode=0,
                    stdout=json.dumps(payload).encode(),
                    stderr=b"",
                ),
            ) as run:
                report = module.run_tool_inventory_probe(account, args)
        command = run.call_args.args[0]
        self.assertIn("PYTHONPATH=/usr/local/lib/hermes-agent", command)
        self.assertIn("get_tool_definitions", command[-1])
        self.assertNotIn("openai-codex", command)
        self.assertNotIn(module.TEST_MODEL, command)
        self.assertFalse(report["modelInvoked"])
        self.assertTrue(report["requiredFileToolsPresent"])
        self.assertEqual(report["requiredFileTools"], sorted(module.REQUIRED_FILE_TOOLS))
        self.assertTrue(report["todoStopGuard"])
        self.assertEqual(report["maxTodoStopNudges"], 8)

    def test_file_probe_uses_real_file_tool_without_model_invocation(self) -> None:
        module = load_module()
        args = SimpleNamespace(
            systemd_run=Path("/usr/bin/systemd-run"),
            user="hermes-rigel",
            timeout=600,
            runtime_root=Path("/usr/local/lib/hermes-agent"),
            hermes_python=Path("/usr/local/lib/hermes-agent/venv/bin/python"),
        )
        payload = {
            path: {
                "error": False,
                "hasContent": True,
                "resolvedMatchesExpected": True,
            }
            for path in (
                "courses/inbox/synthetic-syllabus.md",
                "courses/semester-context.md",
            )
        }
        with tempfile.TemporaryDirectory() as raw:
            account = Path(raw) / "disposable-account"
            account.mkdir()
            with mock.patch.object(
                module.subprocess,
                "run",
                return_value=module.subprocess.CompletedProcess(
                    args=[],
                    returncode=0,
                    stdout=json.dumps(payload).encode(),
                    stderr=b"",
                ),
            ) as run:
                report = module.run_file_read_probe(account, args)
        command = run.call_args.args[0]
        self.assertIn("PYTHONPATH=/usr/local/lib/hermes-agent", command)
        self.assertIn("read_file_tool", command[-1])
        self.assertNotIn("openai-codex", command)
        self.assertFalse(report["modelInvoked"])
        self.assertTrue(report["readsSucceeded"])
        self.assertTrue(report["resolvedMatchesExpected"])

    def test_missing_outputs_report_bounded_synthetic_manifest(self) -> None:
        module = load_module()
        with tempfile.TemporaryDirectory() as raw:
            account = Path(raw)
            courses = account / ".hermes/profiles/rigel/imported-data/courses"
            course = courses / module.COURSE_ID
            course.mkdir(parents=True)
            (course / "syllabus-raw.md").write_text("raw", encoding="utf-8")
            with self.assertRaisesRegex(
                module.SmokeError,
                r"outputs-missing=.*academic-state\.json.*;created=acceptance-1000/syllabus-raw\.md",
            ):
                module.validate_outputs(account, SCHEDULE)

    def test_session_summary_exposes_structure_without_message_content(self) -> None:
        module = load_module()
        with tempfile.TemporaryDirectory() as raw:
            account = Path(raw)
            profile = account / ".hermes/profiles/rigel"
            profile.mkdir(parents=True)
            database = sqlite3.connect(profile / "state.db")
            database.execute(
                """
                CREATE TABLE sessions (
                    id TEXT, model TEXT, billing_provider TEXT,
                    billing_mode TEXT, message_count INTEGER,
                    tool_call_count INTEGER, api_call_count INTEGER,
                    started_at TEXT
                )
                """
            )
            database.execute(
                """
                CREATE TABLE messages (
                    session_id TEXT, role TEXT, tool_name TEXT, content TEXT,
                    tool_calls TEXT
                )
                """
            )
            database.execute(
                "INSERT INTO sessions VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                ("s1", module.TEST_MODEL, "openai-codex", "subscription_included", 3, 1, 2, "2026-08-24T00:00:00Z"),
            )
            database.executemany(
                "INSERT INTO messages VALUES (?, ?, ?, ?, ?)",
                [
                    ("s1", "user", None, "private prompt", None),
                    (
                        "s1",
                        "assistant",
                        None,
                        "private response",
                        json.dumps(
                            [
                                {
                                    "function": {
                                        "name": "read_file",
                                        "arguments": json.dumps(
                                            {
                                                "path": "courses/inbox/synthetic-syllabus.md",
                                                "offset": 1,
                                                "limit": 2000,
                                            }
                                        ),
                                    }
                                }
                            ]
                        ),
                    ),
                    ("s1", "tool", "write_file", "private result", None),
                    (
                        "s1",
                        "tool",
                        "read_file",
                        json.dumps({"error": "File does not exist"}),
                        None,
                    ),
                    (
                        "s1",
                        "tool",
                        "todo",
                        json.dumps(
                            {
                                "summary": {
                                    "pending": 0,
                                    "in_progress": 0,
                                    "completed": 0,
                                    "cancelled": 5,
                                }
                            }
                        ),
                        None,
                    ),
                ],
            )
            database.commit()
            database.close()
            report = module.summarize_session_state(account)
        self.assertEqual(report["billingMode"], "subscription_included")
        self.assertEqual(report["toolNames"], ["read_file", "todo", "write_file"])
        self.assertEqual(
            report["lastTodoSummary"],
            {"pending": 0, "in_progress": 0, "completed": 0, "cancelled": 5},
        )
        self.assertEqual(report["toolOutcomes"]["todo"], {"errors": 0, "results": 1})
        self.assertEqual(
            report["toolOutcomes"]["read_file"],
            {"errors": 1, "results": 1, "errorCategories": {"not-found": 1}},
        )
        self.assertEqual(
            report["readCallShapes"],
            [
                {
                    "pathClass": "syllabus-input",
                    "offsetType": "int",
                    "offset": 1,
                    "limitType": "int",
                    "limit": 2000,
                }
            ],
        )
        self.assertEqual(report["roles"], {"assistant": 1, "tool": 3, "user": 1})
        self.assertNotIn("private prompt", json.dumps(report))
        self.assertNotIn("private response", json.dumps(report))


if __name__ == "__main__":
    unittest.main()
