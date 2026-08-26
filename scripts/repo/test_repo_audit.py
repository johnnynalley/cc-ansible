#!/usr/bin/env python3
"""Focused regressions for repository audit reference resolution."""

from __future__ import annotations

import importlib.machinery
import importlib.util
import json
import re
import subprocess
import tempfile
import unittest
from unittest import mock
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
        (skill_root / "SKILL.md").write_text(
            "---\nname: academic\n---\n"
            "Use `templates/course-state/academic-state.json`.\n"
        )
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
        self.assertIn(
            (
                "files/hermes/profile-skills/rigel/academic/SKILL.md",
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

        skill_path = contract_path.parent / "profile-skills/rigel/academic/SKILL.md"
        generic_errors = repo_audit.reference_errors(
            [skill_path],
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

    def test_reviewed_upstream_source_path_is_not_a_local_repo_reference(self) -> None:
        source = self.root / "inventory/group_vars/hermes_hosts/vars.yml"
        source.parent.mkdir(parents=True)
        reference = "scripts/ci/test_install_ps1_path_migration.ps1"
        source.write_text(f"upstream_paths:\n  - {reference}\n")
        errors = repo_audit.reference_errors(
            [source],
            "scripts",
            re.compile(r"(?<!/)scripts/([^\s`'\")\]\(]+)"),
            ignored_references=repo_audit.UPSTREAM_REPOSITORY_REFERENCES,
        )
        self.assertEqual(errors, [])

    def test_reviewed_profile_runtime_path_is_not_a_repo_reference(self) -> None:
        source = self.root / "scripts/agents/hermes-rigel-workflow-smoke.py"
        source.parent.mkdir(parents=True)
        source.write_text(
            'schedule = CANONICAL_PROFILE / "scripts/hermes-rigel-schedule.py"\n'
        )
        errors = repo_audit.reference_errors(
            [source],
            "scripts",
            re.compile(r"(?<!/)scripts/([^\s`'\")\]\(]+)"),
            ignored_references=repo_audit.PROFILE_RUNTIME_REFERENCES,
        )
        self.assertEqual(errors, [])

    def test_unreviewed_upstream_shaped_path_still_fails(self) -> None:
        source = self.root / "inventory/group_vars/hermes_hosts/other.yml"
        source.parent.mkdir(parents=True)
        source.write_text("upstream_paths:\n  - scripts/tests/missing.ps1\n")
        errors = repo_audit.reference_errors(
            [source],
            "scripts",
            re.compile(r"(?<!/)scripts/([^\s`'\")\]\(]+)"),
            ignored_references=repo_audit.UPSTREAM_REPOSITORY_REFERENCES,
        )
        self.assertEqual(
            errors,
            [
                "inventory/group_vars/hermes_hosts/other.yml references missing "
                "scripts/tests/missing.ps1"
            ],
        )

    def test_hermes_ownership_audit_failure_is_propagated(self) -> None:
        failure = subprocess.CompletedProcess(
            args=[],
            returncode=1,
            stdout="hermes-ownership-audit-error:unclassified-path-reference\n",
        )
        with mock.patch.object(repo_audit.subprocess, "run", return_value=failure):
            self.assertEqual(
                repo_audit.run_hermes_ownership_audit(),
                ["hermes-ownership-audit-error:unclassified-path-reference"],
            )


if __name__ == "__main__":
    unittest.main()
