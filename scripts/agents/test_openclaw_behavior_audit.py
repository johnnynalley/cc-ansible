#!/usr/bin/env python3
"""Tests for the private OpenClaw behavior-canary evidence gate."""

from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

MODULE_PATH = Path(__file__).with_name("openclaw-behavior-audit.py")
SPEC = importlib.util.spec_from_file_location("openclaw_behavior_audit", MODULE_PATH)
assert SPEC and SPEC.loader
audit_module = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = audit_module
SPEC.loader.exec_module(audit_module)


class BehaviorAuditFixture:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.state = root / "state"
        self.workspace = root / "workspace"
        self.state.mkdir()
        self.workspace.mkdir()
        self.started_at_ms = 1_700_000_000_000
        self.nonce = "lineage-123456"
        self.primary_model = "openai/gpt-5.6-sol"
        self.antares_model = "ollama-cloud/deepseek-v4-pro"
        self.dubble_key = "agent:dubble:explicit:behavior-dubble-1"
        self.star_key = "agent:main:explicit:behavior-star-1"
        self.vega_key = "agent:vega:subagent:vega-1"
        self.antares_key = "agent:antares:subagent:antares-1"
        self.rigel_key = "agent:rigel:main:heartbeat"
        self.dubble_marker = "DUBBLE_CANARY_123456"
        self.vega_final = (
            f"Packet {self.nonce}: Cedar costs $24 for two users and supports "
            "MFA plus IMAP; Birch lacks mandatory MFA; the cap is $30."
        )
        self.star_text = (
            "Choose Cedar: two accounts cost $24 per year, stay under the $30 "
            "cap, and meet the required MFA and IMAP constraints."
        )
        self.dubble_result = root / "dubble.json"
        self.star_result = root / "star.json"
        self.heartbeat_event = root / "heartbeat.json"
        self.output = root / "audit.json"
        self.entries: dict[str, dict[str, dict[str, object]]] = {
            agent: {} for agent in audit_module.AGENTS
        }
        self._build()

    def _prompt_report(
        self,
        agent: str,
        session_key: str,
        session_id: str,
        model_reference: str,
        files: list[str],
        tools: list[str],
    ) -> dict[str, object]:
        provider, model = model_reference.split("/", 1)
        workspace = self.workspace if agent == "main" else self.workspace / agent
        workspace.mkdir(exist_ok=True)
        return {
            "source": "run",
            "generatedAt": self.started_at_ms + 1000,
            "sessionId": session_id,
            "sessionKey": session_key,
            "provider": provider,
            "model": model,
            "workspaceDir": str(workspace),
            "injectedWorkspaceFiles": [
                {"name": name, "path": str(workspace / name), "missing": False}
                for name in files
            ],
            "tools": {"entries": [{"name": name} for name in tools]},
        }

    def _entry(
        self,
        agent: str,
        session_key: str,
        session_id: str,
        model_reference: str,
        files: list[str],
        tools: list[str],
        *,
        transcript: Path | None = None,
        spawned_by: str | None = None,
    ) -> dict[str, object]:
        entry: dict[str, object] = {
            "sessionId": session_id,
            "updatedAt": self.started_at_ms + 1000,
            "systemPromptReport": self._prompt_report(
                agent,
                session_key,
                session_id,
                model_reference,
                files,
                tools,
            ),
        }
        if transcript is not None:
            entry["sessionFile"] = str(transcript)
        if spawned_by is not None:
            entry.update(
                {
                    "spawnedBy": spawned_by,
                    "spawnDepth": 1,
                    "subagentRole": "leaf",
                    "status": "done",
                }
            )
        return entry

    def _transcript(
        self, agent: str, name: str, messages: list[dict[str, object]]
    ) -> Path:
        directory = self.state / "agents" / agent / "sessions"
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"{name}.jsonl"
        timestamp = (
            datetime.fromtimestamp((self.started_at_ms + 1000) / 1000, tz=timezone.utc)
            .isoformat()
            .replace("+00:00", "Z")
        )
        rows = [
            {
                "type": "message",
                "id": f"message-{index}",
                "parentId": None if index == 0 else f"message-{index - 1}",
                "timestamp": timestamp,
                "message": message,
            }
            for index, message in enumerate(messages)
        ]
        path.write_text(
            "".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8"
        )
        return path

    @staticmethod
    def _write_agent_result(path: Path, text: str) -> None:
        path.write_text(
            json.dumps({"status": "ok", "result": {"payloads": [{"text": text}]}}),
            encoding="utf-8",
        )

    def _write_stores(self) -> None:
        for agent, entries in self.entries.items():
            directory = self.state / "agents" / agent / "sessions"
            directory.mkdir(parents=True, exist_ok=True)
            (directory / "sessions.json").write_text(
                json.dumps(entries), encoding="utf-8"
            )

    def _build(self) -> None:
        dubble_transcript = self._transcript(
            "dubble",
            "dubble-1",
            [
                {
                    "role": "user",
                    "content": [{"type": "text", "text": "Return the marker."}],
                },
                {
                    "role": "assistant",
                    "content": [{"type": "text", "text": self.dubble_marker}],
                },
            ],
        )
        vega_transcript = self._transcript(
            "vega",
            "vega-1",
            [
                {
                    "role": "user",
                    "content": [{"type": "text", "text": f"Task {self.nonce}"}],
                },
                {
                    "role": "assistant",
                    "content": [{"type": "text", "text": self.vega_final}],
                },
            ],
        )
        antares_transcript = self._transcript(
            "antares",
            "antares-1",
            [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": (
                                f"Review {self.nonce}. Vega actual findings:\n"
                                f"{self.vega_final}"
                            ),
                        }
                    ],
                },
                {
                    "role": "assistant",
                    "content": [
                        {
                            "type": "text",
                            "text": f"PASS {self.nonce}: every hard constraint is covered.",
                        }
                    ],
                },
            ],
        )
        rigel_transcript = self._transcript(
            "rigel",
            "rigel-heartbeat",
            [
                {
                    "role": "user",
                    "content": [{"type": "text", "text": "Heartbeat poll"}],
                },
                {
                    "role": "assistant",
                    "content": [
                        {
                            "type": "toolCall",
                            "name": "heartbeat_respond",
                            "arguments": {
                                "outcome": "no_change",
                                "notify": False,
                                "summary": "No sourced academic event is due.",
                            },
                        }
                    ],
                },
                {
                    "role": "toolResult",
                    "isError": False,
                    "content": [{"type": "tool_result", "text": "recorded"}],
                },
            ],
        )
        complete_facts = (
            "Cedar costs $12 per user per year and supports independent accounts, "
            "MFA, and IMAP. Birch costs $10 total per year and supports independent "
            "accounts and IMAP, but has no MFA. Exactly two accounts are needed, "
            "MFA and IMAP are mandatory, and the cap is $30."
        )
        main_transcript = self._transcript(
            "main",
            "star-1",
            [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": f"Run Star {self.nonce}. {complete_facts}",
                        }
                    ],
                },
                {
                    "role": "assistant",
                    "content": [
                        {
                            "type": "toolCall",
                            "name": "sessions_spawn",
                            "arguments": {
                                "agentId": "vega",
                                "mode": "run",
                                "cleanup": "keep",
                                "task": f"Verify {self.nonce}. {complete_facts}",
                            },
                        }
                    ],
                },
                {
                    "role": "assistant",
                    "content": [
                        {
                            "type": "toolCall",
                            "name": "sessions_yield",
                            "arguments": {},
                        }
                    ],
                },
                {
                    "role": "user",
                    "content": [{"type": "text", "text": self.vega_final}],
                },
                {
                    "role": "assistant",
                    "content": [
                        {
                            "type": "toolCall",
                            "name": "sessions_spawn",
                            "arguments": {
                                "agentId": "antares",
                                "mode": "run",
                                "cleanup": "keep",
                                "task": (
                                    f"Review {self.nonce}. {complete_facts}\n"
                                    f"Vega actual packet:\n{self.vega_final}"
                                ),
                            },
                        }
                    ],
                },
                {
                    "role": "assistant",
                    "content": [
                        {
                            "type": "toolCall",
                            "name": "sessions_yield",
                            "arguments": {},
                        }
                    ],
                },
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": f"PASS {self.nonce}: constraints verified.",
                        }
                    ],
                },
                {
                    "role": "assistant",
                    "content": [{"type": "text", "text": self.star_text}],
                },
            ],
        )
        self.entries["main"][self.star_key] = self._entry(
            "main",
            self.star_key,
            "main-session",
            self.primary_model,
            ["AGENTS.md", "SOUL.md", "USER.md"],
            ["sessions_spawn", "sessions_yield", "read"],
            transcript=main_transcript,
        )
        self.entries["dubble"][self.dubble_key] = self._entry(
            "dubble",
            self.dubble_key,
            "dubble-session",
            self.primary_model,
            ["AGENTS.md", "SOUL.md"],
            ["read", "session_status"],
            transcript=dubble_transcript,
        )
        self.entries["vega"][self.vega_key] = self._entry(
            "vega",
            self.vega_key,
            "vega-session",
            self.primary_model,
            ["AGENTS.md", "SOUL.md"],
            ["read", "session_status"],
            transcript=vega_transcript,
            spawned_by=self.star_key,
        )
        self.entries["antares"][self.antares_key] = self._entry(
            "antares",
            self.antares_key,
            "antares-session",
            self.antares_model,
            ["AGENTS.md", "SOUL.md"],
            ["read", "session_status"],
            transcript=antares_transcript,
            spawned_by=self.star_key,
        )
        self.entries["rigel"][self.rigel_key] = self._entry(
            "rigel",
            self.rigel_key,
            "rigel-session",
            self.primary_model,
            ["HEARTBEAT.md"],
            ["heartbeat_respond", "read", "session_status"],
            transcript=rigel_transcript,
        )
        self._write_stores()
        self._write_agent_result(self.dubble_result, self.dubble_marker)
        self._write_agent_result(self.star_result, self.star_text)
        self.heartbeat_event.write_text(
            json.dumps(
                {
                    "ts": self.started_at_ms + 2000,
                    "status": "ok-token",
                    "reason": "manual",
                    "preview": "No sourced academic event is due.",
                    "silent": True,
                }
            ),
            encoding="utf-8",
        )

    def audit(self) -> dict[str, object]:
        return audit_module.audit_behavior(
            state_root=self.state,
            workspace_root=self.workspace,
            dubble_result=self.dubble_result,
            dubble_session_key=self.dubble_key,
            dubble_marker=self.dubble_marker,
            star_result=self.star_result,
            star_session_key=self.star_key,
            nonce=self.nonce,
            heartbeat_event=self.heartbeat_event,
            heartbeat_session_key=self.rigel_key,
            heartbeat_started_at_ms=self.started_at_ms,
            primary_model=self.primary_model,
            antares_model=self.antares_model,
        )


class BehaviorAuditTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.fixture = BehaviorAuditFixture(Path(self.temporary.name))

    def test_complete_behavior_evidence_passes(self) -> None:
        report = self.fixture.audit()
        self.assertEqual(report["status"], "ok")
        self.assertEqual(report["checks"]["star"]["childCount"], 2)
        self.assertTrue(report["checks"]["star"]["packetPassedToReviewer"])
        self.assertTrue(report["checks"]["rigel"]["event"]["silent"])

    def test_antares_must_receive_exact_vega_packet(self) -> None:
        transcript = Path(
            self.fixture.entries["antares"][self.fixture.antares_key]["sessionFile"]
        )
        text = transcript.read_text(encoding="utf-8")
        transcript.write_text(
            text.replace(self.fixture.vega_final, "A summary was omitted."),
            encoding="utf-8",
        )
        with self.assertRaisesRegex(
            audit_module.BehaviorAuditError, "antares-missing-vega-packet"
        ):
            self.fixture.audit()

    def test_star_spawn_mode_and_cleanup_are_verified(self) -> None:
        transcript = Path(
            self.fixture.entries["main"][self.fixture.star_key]["sessionFile"]
        )
        rows = [json.loads(line) for line in transcript.read_text().splitlines()]
        rows[1]["message"]["content"][0]["arguments"]["mode"] = "session"
        transcript.write_text(
            "".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8"
        )
        with self.assertRaisesRegex(
            audit_module.BehaviorAuditError, "star-spawn-mode-0"
        ):
            self.fixture.audit()

    def test_star_result_must_match_persisted_parent_transcript(self) -> None:
        self.fixture._write_agent_result(
            self.fixture.star_result,
            "Cedar costs $24 under $30 and provides MFA and IMAP for both accounts.",
        )
        with self.assertRaisesRegex(
            audit_module.BehaviorAuditError, "star-result-transcript-mismatch"
        ):
            self.fixture.audit()

    def test_child_parent_lineage_is_required(self) -> None:
        self.fixture.entries["vega"][self.fixture.vega_key]["spawnedBy"] = "wrong"
        self.fixture._write_stores()
        with self.assertRaisesRegex(
            audit_module.BehaviorAuditError, "vega-child-count"
        ):
            self.fixture.audit()

    def test_user_facing_star_answer_rejects_internal_packet_narration(self) -> None:
        self.fixture._write_agent_result(
            self.fixture.star_result,
            "Vega and Antares agree: choose Cedar for $24 under $30 with MFA and IMAP.",
        )
        with self.assertRaisesRegex(
            audit_module.BehaviorAuditError, "star-final-internal-meta"
        ):
            self.fixture.audit()

    def test_effective_dangerous_tool_is_rejected(self) -> None:
        report = self.fixture.entries["main"][self.fixture.star_key][
            "systemPromptReport"
        ]
        report["tools"]["entries"].append({"name": "exec"})
        self.fixture._write_stores()
        with self.assertRaisesRegex(
            audit_module.BehaviorAuditError, "main-dangerous-tool-present"
        ):
            self.fixture.audit()

    def test_rigel_notify_true_is_rejected(self) -> None:
        transcript = Path(
            self.fixture.entries["rigel"][self.fixture.rigel_key]["sessionFile"]
        )
        text = transcript.read_text(encoding="utf-8")
        transcript.write_text(
            text.replace('"notify": false', '"notify": true'), encoding="utf-8"
        )
        with self.assertRaisesRegex(
            audit_module.BehaviorAuditError, "rigel-heartbeat-notify-enabled"
        ):
            self.fixture.audit()

    def test_rigel_visible_text_is_rejected(self) -> None:
        transcript = Path(
            self.fixture.entries["rigel"][self.fixture.rigel_key]["sessionFile"]
        )
        rows = [json.loads(line) for line in transcript.read_text().splitlines()]
        rows[1]["message"]["content"].append({"type": "text", "text": "HEARTBEAT_OK"})
        transcript.write_text(
            "".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8"
        )
        with self.assertRaisesRegex(
            audit_module.BehaviorAuditError, "rigel-visible-assistant-text"
        ):
            self.fixture.audit()

    def test_transcript_outside_state_root_is_rejected(self) -> None:
        outside = self.fixture.root / "outside.jsonl"
        outside.write_text("{}\n", encoding="utf-8")
        self.fixture.entries["vega"][self.fixture.vega_key]["sessionFile"] = str(
            outside
        )
        self.fixture._write_stores()
        with self.assertRaisesRegex(
            audit_module.BehaviorAuditError, "vega-file-outside-root"
        ):
            self.fixture.audit()

    def test_transcript_through_internal_symlink_is_rejected(self) -> None:
        target = self.fixture.state / "agents" / "vega" / "sessions"
        alias = self.fixture.state / "vega-session-alias"
        alias.symlink_to(target, target_is_directory=True)
        self.fixture.entries["vega"][self.fixture.vega_key]["sessionFile"] = str(
            alias / "vega-1.jsonl"
        )
        self.fixture._write_stores()
        with self.assertRaisesRegex(
            audit_module.BehaviorAuditError, "vega-file-symlink-component"
        ):
            self.fixture.audit()


if __name__ == "__main__":
    unittest.main()
