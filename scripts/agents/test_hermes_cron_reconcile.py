#!/usr/bin/env python3
"""Regression tests for native Hermes cron reconciliation and delivery state."""

from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace


DIRECTORY = Path(__file__).parent


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


RECONCILE = load_module(
    "hermes_cron_reconcile",
    DIRECTORY / "hermes-cron-reconcile.py",
)
DELIVERY = load_module(
    "hermes_cron_delivery",
    DIRECTORY / "hermes_cron_delivery.py",
)


class FakeCron:
    def __init__(self, jobs=None):
        self.jobs = list(jobs or [])
        self.remove_result = True

    def parse_schedule(self, schedule):
        if schedule == "every 1h":
            return {"kind": "interval", "minutes": 60, "display": "every 60m"}
        return {"kind": "test", "display": schedule}

    def list_jobs(self, include_disabled=False):
        del include_disabled
        return [dict(job) for job in self.jobs]

    def create_job(self, **values):
        parsed_schedule = self.parse_schedule(values["schedule"])
        job = {
            "id": f"job-{len(self.jobs) + 1}",
            **values,
            "enabled": True,
            "state": "scheduled",
            "schedule": parsed_schedule,
            "schedule_display": parsed_schedule["display"],
            "skills": values.get("skills") or [],
            "enabled_toolsets": values.get("enabled_toolsets"),
        }
        self.jobs.append(job)
        return dict(job)

    def update_job(self, job_id, updates):
        for job in self.jobs:
            if job["id"] != job_id:
                continue
            job.update(updates)
            if isinstance(job.get("schedule"), str):
                parsed_schedule = self.parse_schedule(job["schedule"])
                job["schedule"] = parsed_schedule
                job["schedule_display"] = parsed_schedule["display"]
            return dict(job)
        return None

    def remove_job(self, job_id):
        if not self.remove_result:
            return False
        before = len(self.jobs)
        self.jobs = [job for job in self.jobs if job["id"] != job_id]
        return len(self.jobs) != before

    def resume_job(self, job_id):
        for job in self.jobs:
            if job["id"] == job_id:
                job["enabled"] = True
                job["state"] = "scheduled"
                return dict(job)
        return None


class ReconcileTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.home = Path(self.temporary.name)
        (self.home / "scripts").mkdir()
        (self.home / "state").mkdir()
        (self.home / "scripts" / "task.py").write_text("print('ok')\n")
        self.manifest = self.home / "manifest.json"
        self.job = {
            "key": "test-alert",
            "name": "test-alert",
            "schedule": "every 30m",
            "prompt": "",
            "deliver": "discord:1488752822466904256",
            "script": "task.py",
            "noAgent": True,
        }

    def tearDown(self):
        self.temporary.cleanup()

    def args(self, apply: bool, operation: str | None = None, keys=None):
        return SimpleNamespace(
            home=self.home,
            manifest=self.manifest,
            profile="astra",
            apply=apply,
            check=not apply,
            operation=operation,
            keys=list(keys or []),
        )

    def write_manifest(self, jobs=None):
        selected = [self.job] if jobs is None else jobs
        self.manifest.write_text(
            json.dumps(
                {
                    "schemaVersion": 1,
                    "profile": "astra",
                    "jobs": selected,
                }
            )
        )

    def test_create_then_zero_drift(self):
        self.write_manifest()
        api = FakeCron()
        RECONCILE.native_api = lambda: api
        self.assertEqual(
            RECONCILE.reconcile(self.args(True)),
            [{"key": "test-alert", "action": "create"}],
        )
        self.assertEqual(RECONCILE.reconcile(self.args(False)), [])

    def test_native_interval_display_normalization_has_zero_drift(self):
        self.job["schedule"] = "every 1h"
        self.write_manifest()
        api = FakeCron()
        RECONCILE.native_api = lambda: api
        self.assertEqual(
            RECONCILE.reconcile(self.args(True)),
            [{"key": "test-alert", "action": "create"}],
        )
        self.assertEqual(api.jobs[0]["schedule_display"], "every 60m")
        self.assertEqual(RECONCILE.reconcile(self.args(False)), [])

    def test_adopts_only_explicit_single_name_match(self):
        adopted = dict(self.job)
        adopted["adoptExisting"] = True
        self.write_manifest([adopted])
        api = FakeCron(
            [
                {
                    "id": "legacy-id",
                    "name": "test-alert",
                    "prompt": "",
                    "deliver": "discord:1488752822466904256",
                    "script": "task.py",
                    "no_agent": True,
                    "model": None,
                    "provider": None,
                    "skills": [],
                    "enabled_toolsets": None,
                    "workdir": None,
                    "schedule_display": "every 30m",
                    "enabled": True,
                    "state": "scheduled",
                    "origin": None,
                }
            ]
        )
        RECONCILE.native_api = lambda: api
        self.assertEqual(
            RECONCILE.reconcile(self.args(True)),
            [{"key": "test-alert", "action": "update"}],
        )
        self.assertEqual(api.jobs[0]["id"], "legacy-id")
        self.assertEqual(api.jobs[0]["origin"]["key"], "test-alert")

    def test_failed_native_remove_fails_closed(self):
        self.write_manifest([])
        managed = {
            "id": "stale",
            "name": "stale",
            "origin": {
                "kind": RECONCILE.ORIGIN_KIND,
                "key": "stale",
                "profile": "astra",
                "schemaVersion": 1,
            },
        }
        api = FakeCron([managed])
        api.remove_result = False
        RECONCILE.native_api = lambda: api
        with self.assertRaisesRegex(RECONCILE.ReconcileError, "native-remove-failed"):
            RECONCILE.reconcile(self.args(True))

    def test_check_reports_drift_without_mutation(self):
        self.write_manifest()
        api = FakeCron()
        RECONCILE.native_api = lambda: api
        self.assertEqual(
            RECONCILE.reconcile(self.args(False)),
            [{"key": "test-alert", "action": "create"}],
        )
        self.assertEqual(api.jobs, [])

    def test_targeted_restore_preserves_unselected_managed_jobs(self):
        self.write_manifest()
        api = FakeCron()
        RECONCILE.native_api = lambda: api
        RECONCILE.reconcile(self.args(True))
        api.jobs[0]["prompt"] = "stale"
        api.jobs.append(
            {
                "id": "unselected",
                "name": "unselected",
                "origin": {
                    "kind": RECONCILE.ORIGIN_KIND,
                    "key": "unselected",
                    "profile": "astra",
                    "schemaVersion": 1,
                },
            }
        )

        self.assertEqual(
            RECONCILE.reconcile(
                self.args(True, operation="restore", keys=["test-alert"])
            ),
            [{"key": "test-alert", "action": "update"}],
        )
        self.assertEqual({job["id"] for job in api.jobs}, {"job-1", "unselected"})

    def test_targeted_reconcile_rejects_unknown_key(self):
        self.write_manifest()
        RECONCILE.native_api = lambda: FakeCron()
        with self.assertRaisesRegex(RECONCILE.ReconcileError, "unknown-target-key"):
            RECONCILE.reconcile(self.args(False, keys=["missing"]))

    def test_seed_preserves_native_edits(self):
        self.write_manifest()
        edited = {
            "id": "native-edit",
            "name": "test-alert",
            "prompt": "",
            "deliver": "discord:1488752822466904256",
            "script": "task.py",
            "no_agent": True,
            "model": None,
            "provider": None,
            "skills": [],
            "enabled_toolsets": None,
            "context_from": None,
            "workdir": None,
            "schedule_display": "every 2h",
            "enabled": True,
            "state": "scheduled",
            "origin": RECONCILE.origin_for(self.job, "astra"),
        }
        api = FakeCron([edited])
        RECONCILE.native_api = lambda: api
        self.assertEqual(RECONCILE.reconcile(self.args(False, "seed")), [])
        self.assertEqual(api.jobs[0]["schedule_display"], "every 2h")

    def test_seed_creates_a_missing_job(self):
        self.write_manifest()
        api = FakeCron()
        RECONCILE.native_api = lambda: api
        self.assertEqual(
            RECONCILE.reconcile(self.args(False, "seed")),
            [{"key": "test-alert", "action": "create"}],
        )
        self.assertEqual(len(api.jobs), 1)

    def test_seed_refuses_to_adopt_an_unmanaged_name_collision(self):
        adopted = dict(self.job)
        adopted["adoptExisting"] = True
        self.write_manifest([adopted])
        api = FakeCron([{"id": "native", "name": "test-alert", "origin": None}])
        RECONCILE.native_api = lambda: api
        with self.assertRaisesRegex(RECONCILE.ReconcileError, "seed-name-collision"):
            RECONCILE.reconcile(self.args(False, "seed"))

    def test_agent_job_requires_profile_workdir_and_preserves_continuity(self):
        agent = {
            "key": "daily-brief",
            "name": "daily-brief",
            "schedule": "0 7 * * *",
            "prompt": "Compose the brief.",
            "deliver": "local",
            "script": "task.py",
            "noAgent": False,
            "continuity": True,
            "workdir": str(self.home),
        }
        self.write_manifest([agent])
        api = FakeCron()
        RECONCILE.native_api = lambda: api
        self.assertEqual(
            RECONCILE.reconcile(self.args(True)),
            [{"key": "daily-brief", "action": "create"}],
        )
        self.assertEqual(api.jobs[0]["context_from"], ["self"])
        self.assertEqual(api.jobs[0]["workdir"], str(self.home))
        self.assertEqual(RECONCILE.reconcile(self.args(False)), [])

    def test_agent_job_without_profile_workdir_fails_closed(self):
        agent = {
            "key": "daily-brief",
            "name": "daily-brief",
            "schedule": "0 7 * * *",
            "prompt": "Compose the brief.",
            "deliver": "local",
            "script": None,
            "noAgent": False,
        }
        self.write_manifest([agent])
        RECONCILE.native_api = lambda: FakeCron()
        with self.assertRaisesRegex(
            RECONCILE.ReconcileError, "profile-workdir-required:daily-brief"
        ):
            RECONCILE.reconcile(self.args(False))

    def test_inherited_route_clears_existing_model_pin(self):
        agent = {
            "key": "daily-brief",
            "name": "daily-brief",
            "schedule": "0 7 * * *",
            "prompt": "Compose the brief.",
            "deliver": "local",
            "script": None,
            "noAgent": False,
            "workdir": str(self.home),
        }
        self.write_manifest([agent])
        existing = {
            "id": "pinned-job",
            "name": "daily-brief",
            "prompt": "Compose the brief.",
            "deliver": "local",
            "script": None,
            "no_agent": False,
            "model": "gpt-5.4-mini",
            "provider": "openai-codex",
            "skills": [],
            "enabled_toolsets": None,
            "context_from": None,
            "workdir": str(self.home),
            "schedule_display": "0 7 * * *",
            "enabled": True,
            "state": "scheduled",
            "origin": RECONCILE.origin_for(agent, "astra"),
        }
        api = FakeCron([existing])
        RECONCILE.native_api = lambda: api
        self.assertEqual(
            RECONCILE.reconcile(self.args(True)),
            [{"key": "daily-brief", "action": "update"}],
        )
        self.assertIsNone(api.jobs[0]["model"])
        self.assertIsNone(api.jobs[0]["provider"])
        self.assertEqual(RECONCILE.reconcile(self.args(False)), [])


class DeliveryLedgerTests(unittest.TestCase):
    def test_success_commits_pending_and_failure_requests_retry(self):
        now = datetime(2026, 8, 14, tzinfo=timezone.utc)
        status = {
            "lastRunAt": "2026-08-14T00:00:00+00:00",
            "lastStatus": "ok",
            "lastDeliveryError": None,
        }
        pending = DELIVERY.stage(["one"], "message", status, now)
        self.assertEqual(DELIVERY.reconcile(pending, status)[0], "waiting")
        success = {**status, "lastRunAt": "2026-08-14T00:01:00+00:00"}
        self.assertEqual(DELIVERY.reconcile(pending, success)[0], "delivered")
        failure = {
            **success,
            "lastStatus": "error",
            "lastDeliveryError": "Discord unavailable",
        }
        disposition, retry = DELIVERY.reconcile(pending, failure)
        self.assertEqual(disposition, "retry")
        self.assertEqual(retry["priorLastRunAt"], failure["lastRunAt"])


if __name__ == "__main__":
    unittest.main()
