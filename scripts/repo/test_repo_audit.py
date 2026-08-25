#!/usr/bin/env python3
"""Focused regressions for repository audit reference resolution."""

from __future__ import annotations

import importlib.machinery
import importlib.util
import json
import re
import tempfile
import unittest
from pathlib import Path


AUDIT_PATH = Path(__file__).with_name("repo-audit")
LOADER = importlib.machinery.SourceFileLoader("repo_audit", str(AUDIT_PATH))
SPEC = importlib.util.spec_from_loader(LOADER.name, LOADER)
assert SPEC is not None
repo_audit = importlib.util.module_from_spec(SPEC)
LOADER.exec_module(repo_audit)


class RepoAuditReferenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)
        self.previous_root = repo_audit.ROOT
        repo_audit.ROOT = self.root

    def tearDown(self) -> None:
        repo_audit.ROOT = self.previous_root
        self.temporary_directory.cleanup()

    def write_contract(self, include_support: bool = True) -> Path:
        skill_root = self.root / "files/hermes/profile-skills/rigel/academic"
        skill_root.mkdir(parents=True)
        (skill_root / "SKILL.md").write_text("---\nname: academic\n---\n")
        if include_support:
            support = skill_root / "templates/course-state/academic-state.json"
            support.parent.mkdir(parents=True)
            support.write_text("{}\n")
        contract_path = self.root / "files/hermes/profile-skills-contract.json"
        contract_path.parent.mkdir(parents=True, exist_ok=True)
        contract_path.write_text(
            json.dumps(
                {
                    "profiles": {
                        "rigel": {
                            "skills": [
                                {
                                    "name": "academic",
                                    "source": (
                                        "files/hermes/profile-skills/rigel/academic/"
                                        "SKILL.md"
                                    ),
                                    "supportingFiles": [
                                        {
                                            "path": (
                                                "templates/course-state/"
                                                "academic-state.json"
                                            ),
                                            "sha256": "0" * 64,
                                        }
                                    ],
                                }
                            ]
                        }
                    }
                }
            )
        )
        return contract_path

    def test_skill_relative_template_reference_is_not_repo_template(self) -> None:
        contract_path = self.write_contract()
        errors, ignored = repo_audit.profile_skill_contract_reference_errors(
            [contract_path]
        )
        self.assertEqual(errors, [])
        self.assertIn(
            (
                "files/hermes/profile-skills-contract.json",
                "templates/course-state/academic-state.json",
            ),
            ignored,
        )
        generic_errors = repo_audit.reference_errors(
            [contract_path],
            "templates",
            re.compile(r"(?:templates/|\.\./templates/)([^\s`'\")\]\(]+)"),
            ignored_references=ignored,
        )
        self.assertEqual(generic_errors, [])

    def test_missing_skill_support_is_reported(self) -> None:
        contract_path = self.write_contract(include_support=False)
        errors, _ = repo_audit.profile_skill_contract_reference_errors(
            [contract_path]
        )
        self.assertEqual(len(errors), 1)
        self.assertIn("references missing skill support", errors[0])

    def test_normal_missing_repo_template_is_still_reported(self) -> None:
        document = self.root / "docs/example.md"
        document.parent.mkdir(parents=True)
        document.write_text("Use templates/hermes/missing.j2.\n")
        errors = repo_audit.reference_errors(
            [document],
            "templates",
            re.compile(r"(?:templates/|\.\./templates/)([^\s`'\")\]\(]+)"),
        )
        self.assertEqual(
            errors,
            ["docs/example.md references missing templates/hermes/missing.j2"],
        )


if __name__ == "__main__":
    unittest.main()
