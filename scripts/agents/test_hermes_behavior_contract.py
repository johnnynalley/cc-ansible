#!/usr/bin/env python3
"""Static regressions for Hermes reasoning and self-evolution policy."""

from __future__ import annotations

import json
import unittest
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).parents[2]
CONTRACT = ROOT / "files" / "hermes" / "behavior-contract.json"
REGRESSIONS = ROOT / "files" / "hermes" / "behavior-regressions.json"
EXPECTED_CASES = {
    "authoritative-alert-evidence",
    "compatibility-performance-recommendation",
    "current-regional-evidence",
    "direct-decision-first",
    "expected-absence-is-data",
    "explicit-scope-and-preference",
    "incident-root-cause-before-suppression",
    "purchase-commitment-reconciliation",
    "reversible-recommendation-latency",
    "self-evolution-generalization",
    "star-concise-private-review",
    "busy-followup-fifo",
    "thread-antecedent-resolution",
    "walkthrough-real-branch",
}


class HermesBehaviorContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
        cls.regressions = json.loads(REGRESSIONS.read_text(encoding="utf-8"))

    def test_reasoning_router_is_semantic_not_phrase_based(self) -> None:
        routing = self.contract["routing"]
        self.assertEqual(
            routing["selector"], "semantic-intent-stakes-uncertainty-state"
        )
        self.assertFalse(routing["phraseMatching"])
        self.assertFalse(routing["keywordTriggering"])
        self.assertTrue(routing["fullThreadRequired"])
        self.assertTrue(routing["durableStateRequiredWhenRelevant"])

    def test_user_output_is_one_normal_answer(self) -> None:
        output = self.contract["output"]
        self.assertTrue(output["directAnswerFirst"])
        self.assertTrue(output["singleUserFacingAnswer"])
        self.assertTrue(output["privateReviewerEvidence"])
        for key in {
            "internalReasoningVisible",
            "toolPlumbingVisible",
            "correctionTransactionVisible",
            "routineValidationNarrationVisible",
        }:
            self.assertFalse(output[key])

    def test_busy_followups_are_fifo_and_do_not_supersede_active_answers(self) -> None:
        continuity = self.contract["continuity"]
        self.assertEqual(continuity["busyInputMode"], "queue")
        self.assertTrue(continuity["oneTurnPerFollowUp"])
        self.assertFalse(continuity["unfinishedAnswerMayBeSuperseded"])
        self.assertTrue(continuity["explicitStopOrResetMayInterrupt"])

    def test_native_self_evolution_is_approval_gated(self) -> None:
        evolution = self.contract["selfEvolution"]
        self.assertEqual(evolution["mechanism"], "hermes-native-background-review")
        self.assertEqual(evolution["selection"], "semantic-context-review")
        self.assertEqual(evolution["memoryWrites"], "stage-for-owner-approval")
        self.assertEqual(evolution["skillWrites"], "stage-for-owner-approval")
        self.assertTrue(evolution["pendingWritesSurviveRestart"])
        self.assertFalse(evolution["automaticApply"])
        self.assertFalse(evolution["selfApproval"])
        self.assertFalse(evolution["rootPolicyWritableByAgent"])
        self.assertFalse(evolution["toolAuthorityWritableByAgent"])
        self.assertEqual(evolution["notifications"], "off")
        self.assertEqual(len(evolution["reviewSurfaces"]), 7)

    def test_policy_changes_cannot_route_to_agent_memory_or_skills(self) -> None:
        routing = self.contract["selfEvolution"]["proposalRouting"]
        self.assertEqual(routing["user-preference"], "user-memory")
        self.assertEqual(routing["stable-environment-fact"], "profile-memory")
        self.assertEqual(routing["reusable-procedure"], "profile-skill")
        for category in {"behavior-policy", "security-policy", "deployment-policy"}:
            self.assertEqual(routing[category], "owner-managed-source")

    def test_correction_policy_rejects_incident_rule_accumulation(self) -> None:
        corrections = self.contract["corrections"]
        self.assertTrue(corrections["fixCurrentAnswerFirst"])
        self.assertTrue(corrections["rootCauseClassRequired"])
        self.assertTrue(corrections["generalizeBeforeProposal"])
        self.assertTrue(corrections["preventionRegressionRequired"])
        self.assertEqual(
            corrections["foregroundProposalNarration"],
            "only-when-owner-action-required",
        )
        self.assertEqual(corrections["incidentSpecificRuleDefault"], "reject")
        self.assertEqual(
            corrections["existingControlFailureDisposition"],
            "regression-or-enforcement-proposal",
        )
        self.assertFalse(corrections["generatedOutputMayServeAsEvidence"])

    def test_profile_operating_contracts_are_regular_repo_files(self) -> None:
        expected = {"astra", "dubble", "rigel"}
        self.assertEqual(set(self.contract["profilePolicies"]), expected)
        for profile, source in self.contract["profilePolicies"].items():
            path = PurePosixPath(source)
            self.assertFalse(path.is_absolute())
            self.assertNotIn("..", path.parts)
            full_path = ROOT / path
            self.assertTrue(full_path.is_file(), profile)
            self.assertFalse(full_path.is_symlink(), profile)

    def test_regression_corpus_is_complete_and_sanitized(self) -> None:
        self.assertEqual(self.regressions["schemaVersion"], 1)
        self.assertEqual(self.regressions["mode"], "promotion-cases")
        cases = self.regressions["cases"]
        ids = [case["id"] for case in cases]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(set(ids), EXPECTED_CASES)
        for case in cases:
            self.assertEqual(
                set(case),
                {
                    "id",
                    "risk",
                    "exerciseMode",
                    "scenario",
                    "prompt",
                    "required",
                    "forbidden",
                },
            )
            self.assertIn(case["risk"], {"medium", "high", "blocking"})
            self.assertIn(
                case["exerciseMode"],
                {
                    "isolated-model",
                    "live-evidence",
                    "deterministic-idle",
                    "gateway-integration",
                },
            )
            self.assertTrue(case["scenario"].strip())
            self.assertTrue(case["prompt"].strip())
            self.assertTrue(case["required"].strip())
            self.assertTrue(case["forbidden"].strip())
            serialized = json.dumps(case)
            self.assertNotIn("/home/", serialized)
            self.assertNotIn("@Jaah", serialized)
            self.assertNotIn("LuhJaah", serialized)

    def test_promotion_cases_assign_real_execution_owners(self) -> None:
        by_id = {case["id"]: case for case in self.regressions["cases"]}
        self.assertEqual(
            by_id["expected-absence-is-data"]["exerciseMode"],
            "deterministic-idle",
        )
        self.assertEqual(
            by_id["current-regional-evidence"]["exerciseMode"],
            "live-evidence",
        )
        self.assertEqual(
            by_id["star-concise-private-review"]["exerciseMode"],
            "gateway-integration",
        )
        self.assertEqual(
            by_id["busy-followup-fifo"]["exerciseMode"],
            "gateway-integration",
        )
        self.assertEqual(
            sum(
                case["exerciseMode"] == "isolated-model"
                for case in self.regressions["cases"]
            ),
            10,
        )

    def test_every_transcript_derived_failure_is_promotion_blocking_or_high(
        self,
    ) -> None:
        for case in self.regressions["cases"]:
            self.assertIn(case["risk"], {"high", "blocking"})

    def test_operating_contracts_do_not_reintroduce_control_tokens(self) -> None:
        for source in self.contract["profilePolicies"].values():
            content = (ROOT / source).read_text(encoding="utf-8")
            self.assertNotIn("HEARTBEAT_OK", content)
            self.assertNotIn("NO_REPLY", content)
            self.assertNotIn("Correction transaction", content)


if __name__ == "__main__":
    unittest.main()
