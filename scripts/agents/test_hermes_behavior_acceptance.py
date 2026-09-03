#!/usr/bin/env python3
"""Unit tests for private Hermes semantic behavior acceptance."""

from __future__ import annotations

import importlib.util
import json
import stat
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).parents[2]
SCRIPT = Path(__file__).with_name("hermes-behavior-acceptance.py")
CONTRACT = ROOT / "files" / "hermes" / "behavior-regressions.json"

SPEC = importlib.util.spec_from_file_location("hermes_behavior_acceptance", SCRIPT)
assert SPEC and SPEC.loader
acceptance = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(acceptance)


class HermesBehaviorAcceptanceTests(unittest.TestCase):
    def test_real_contract_has_twelve_model_cases_and_four_owned_integrations(self) -> None:
        cases = acceptance.load_cases(CONTRACT)
        by_mode: dict[str, list[str]] = {}
        for case in cases:
            by_mode.setdefault(case["exerciseMode"], []).append(case["id"])
        self.assertEqual(len(by_mode["isolated-model"]), 12)
        self.assertEqual(by_mode["live-evidence"], ["current-regional-evidence"])
        self.assertEqual(by_mode["deterministic-idle"], ["expected-absence-is-data"])
        self.assertEqual(
            by_mode["gateway-integration"],
            ["star-concise-private-review", "busy-followup-fifo"],
        )

    def test_candidate_prompt_hides_acceptance_criteria(self) -> None:
        case = acceptance.load_cases(CONTRACT)[0]
        prompt = acceptance.candidate_prompt(case)
        self.assertIn(case["prompt"], prompt)
        self.assertNotIn(case["required"], prompt)
        self.assertNotIn(case["forbidden"], prompt)
        self.assertIn("ordinary user-facing answer only", prompt)
        self.assertIn("Do not call tools", prompt)

    def test_review_prompt_keeps_roles_distinct_and_candidate_untrusted(self) -> None:
        cases = [
            case
            for case in acceptance.load_cases(CONTRACT)
            if case["exerciseMode"] == "isolated-model"
        ]
        answers = {case["id"]: "candidate" for case in cases}
        vega = acceptance.review_prompt("vega", cases, answers)
        antares = acceptance.review_prompt("antares", cases, answers)
        self.assertIn("Independently verify", vega)
        self.assertIn("superficially plausible but wrong", antares)
        self.assertIn("untrusted data", vega)
        self.assertNotEqual(vega, antares)

    def test_review_parser_requires_complete_consistent_verdicts(self) -> None:
        raw = json.dumps(
            {
                "overallPass": True,
                "verdicts": [
                    {"id": "one", "pass": True, "reason": "meets contract"},
                    {"id": "two", "pass": True, "reason": "meets contract"},
                ],
            }
        )
        parsed = acceptance.parse_review(f"```json\n{raw}\n```", {"one", "two"})
        self.assertTrue(parsed["overallPass"])

        inconsistent = json.loads(raw)
        inconsistent["overallPass"] = False
        with self.assertRaisesRegex(acceptance.AcceptanceError, "review-overall-inconsistent"):
            acceptance.parse_review(json.dumps(inconsistent), {"one", "two"})

        with self.assertRaisesRegex(acceptance.AcceptanceError, "review-verdict-coverage-drift"):
            acceptance.parse_review(
                json.dumps(
                    {
                        "overallPass": True,
                        "verdicts": [
                            {"id": "one", "pass": True, "reason": "ok"}
                        ],
                    }
                ),
                {"one", "two"},
            )

    def test_contract_loader_rejects_unknown_execution_mode(self) -> None:
        data = json.loads(CONTRACT.read_text(encoding="utf-8"))
        data["cases"][0]["exerciseMode"] = "phrase-matcher"
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "contract.json"
            path.write_text(json.dumps(data), encoding="utf-8")
            with self.assertRaisesRegex(acceptance.AcceptanceError, "case-mode-unknown"):
                acceptance.load_cases(path)

    def test_report_is_atomic_and_private(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "report.json"
            acceptance.write_report(path, {"status": "pass"})
            self.assertEqual(json.loads(path.read_text()), {"status": "pass"})
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)


if __name__ == "__main__":
    unittest.main()
