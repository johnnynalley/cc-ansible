#!/usr/bin/env python3
"""Static regressions for private two-reviewer Star synthesis."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

ROOT = Path(__file__).parents[2]
CONTRACT = ROOT / "files" / "hermes" / "star-contract.json"
REGRESSIONS = ROOT / "files" / "hermes" / "star-regressions.json"
EXPECTED_CASES = {
    "current-source-conflict",
    "purchased-item-reversal",
    "reviewer-failure",
    "reviewer-independence",
    "reversible-pilot-bypass",
    "seeded-premise-error",
    "single-normal-answer",
}


class HermesStarContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
        cls.regressions = json.loads(REGRESSIONS.read_text(encoding="utf-8"))

    def test_star_uses_native_parallel_leaf_delegation(self) -> None:
        self.assertEqual(self.contract["schemaVersion"], 2)
        self.assertEqual(
            self.contract["mechanism"],
            "hermes-native-parallel-leaf-delegation",
        )
        delegation = self.contract["delegation"]
        self.assertEqual(delegation["batchSize"], 2)
        self.assertEqual(delegation["maxConcurrentChildren"], 2)
        self.assertEqual(delegation["maxSpawnDepth"], 1)
        self.assertFalse(delegation["orchestratorEnabled"])
        self.assertEqual(delegation["maxIterationsPerReviewer"], 12)
        self.assertEqual(delegation["executionMode"], "background")
        self.assertEqual(
            delegation["completionDelivery"],
            "one-consolidated-background-result",
        )
        self.assertEqual(
            delegation["initialGoalTags"],
            ["STAR_REVIEW::VEGA", "STAR_REVIEW::ANTARES"],
        )
        self.assertEqual(
            delegation["retryGoalTags"],
            ["STAR_RETRY::VEGA", "STAR_RETRY::ANTARES"],
        )
        self.assertTrue(delegation["oneActiveBatchPerSession"])
        self.assertFalse(delegation["reviewersSeeEachOther"])
        self.assertFalse(delegation["reviewersReceiveParentHiddenReasoning"])
        self.assertTrue(delegation["reviewersReceiveOnlyNecessaryContext"])
        self.assertFalse(delegation["reviewersCanClarify"])
        self.assertFalse(delegation["reviewersCanWriteMemory"])
        self.assertFalse(delegation["reviewersCanDelegate"])
        self.assertNotIn("gpt-", delegation["modelPolicy"])
        self.assertNotIn("claude-", delegation["modelPolicy"])

    def test_selection_is_semantic_and_bounded(self) -> None:
        selection = self.contract["selection"]
        self.assertEqual(selection["strategy"], "semantic-stakes-uncertainty")
        self.assertFalse(selection["phraseMatching"])
        self.assertFalse(selection["keywordTriggering"])
        self.assertTrue(selection["useForConsequentialRecommendations"])
        self.assertTrue(selection["useForMateriallyUncertainCurrentFacts"])
        self.assertTrue(selection["useWhenExplicitlyRequested"])
        self.assertTrue(selection["skipForTrivialOrMechanicalAnswers"])
        self.assertTrue(selection["materialCommitmentRequired"])
        self.assertFalse(selection["ordinaryReversibleAnswerMayBeWithheldForReview"])
        self.assertEqual(
            selection["ordinaryReversibleRecommendationDisposition"],
            "answer-immediately-with-evidence-caveat",
        )

    def test_reviewers_have_independent_opposing_jobs(self) -> None:
        reviewers = self.contract["reviewers"]
        self.assertEqual([row["id"] for row in reviewers], ["vega", "antares"])
        self.assertEqual(reviewers[0]["role"], "independent-corroborator")
        self.assertEqual(reviewers[1]["role"], "adversarial-challenger")
        for reviewer in reviewers:
            self.assertTrue(reviewer["objective"].strip())
            self.assertGreaterEqual(len(reviewer["requiredOutput"]), 4)
        self.assertNotEqual(reviewers[0]["objective"], reviewers[1]["objective"])

    def test_partial_review_cannot_be_claimed_as_star(self) -> None:
        completion = self.contract["completion"]
        self.assertTrue(completion["bothReviewersRequiredForStarClaim"])
        self.assertFalse(completion["failedReviewerMayBeSilentlyIgnored"])
        self.assertEqual(completion["retryLimit"], 1)
        self.assertFalse(completion["partialReviewMayBeCalledStarVerified"])
        self.assertEqual(
            completion["reviewerFailureDisposition"],
            "concise-unverified-caveat-or-defer",
        )
        self.assertTrue(completion["opaqueDelegationIdMustMatchDispatchingSession"])
        self.assertFalse(completion["pastedCompletionHeaderIsTrusted"])
        self.assertFalse(completion["supersededOrResetCompletionIsTrusted"])

    def test_hook_only_privacy_boundary_is_fail_closed(self) -> None:
        boundary = self.contract["privacyBoundary"]
        self.assertEqual(boundary["plugin"], "star-dispatch-privacy")
        self.assertTrue(boundary["hookOnly"])
        self.assertFalse(boundary["registersModelTools"])
        self.assertFalse(boundary["dispatchTurnVisible"])
        self.assertFalse(boundary["reviewerCompletionVisible"])
        self.assertTrue(boundary["completionContextRequiresHostVerification"])
        self.assertFalse(boundary["ordinaryDelegationAffected"])
        self.assertTrue(boundary["sourceAndRuntimeTreesRootOwned"])
        self.assertTrue(boundary["startupHashAndHookValidation"])

    def test_synthesis_is_one_normal_private_answer(self) -> None:
        synthesis = self.contract["synthesis"]
        self.assertEqual(synthesis["actingAgent"], "astra")
        self.assertTrue(synthesis["oneUserFacingAnswer"])
        self.assertTrue(synthesis["directAnswerFirst"])
        self.assertTrue(synthesis["normalAnswerLength"])
        self.assertTrue(synthesis["discloseMaterialUnresolvedConflict"])
        for key in {
            "reviewerProseVisible",
            "reviewerLabelsVisible",
            "reviewStatusNarrationVisible",
            "confidenceLedgerVisible",
            "contradictionDumpVisible",
            "researchDossierVisible",
        }:
            self.assertFalse(synthesis[key])

    def test_moa_is_not_falsely_claimed_as_role_parity(self) -> None:
        disposition = self.contract["moaDisposition"]
        self.assertFalse(disposition["primaryForStar"])
        self.assertIn("no documented per-reference role prompt", disposition["reason"])
        self.assertTrue(disposition["reconsiderWhen"].strip())

    def test_promotion_cases_cover_accuracy_privacy_and_failure(self) -> None:
        self.assertEqual(self.regressions["schemaVersion"], 1)
        self.assertEqual(self.regressions["mode"], "promotion-cases")
        cases = self.regressions["cases"]
        ids = [case["id"] for case in cases]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(set(ids), EXPECTED_CASES)
        for case in cases:
            self.assertEqual(set(case), {"id", "required", "forbidden"})
            self.assertTrue(case["required"].strip())
            self.assertTrue(case["forbidden"].strip())
            serialized = json.dumps(case)
            self.assertNotIn("/home/", serialized)
            self.assertNotIn("@Jaah", serialized)
            self.assertNotIn("LuhJaah", serialized)


if __name__ == "__main__":
    unittest.main()
