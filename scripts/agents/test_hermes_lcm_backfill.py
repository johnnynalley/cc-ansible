#!/usr/bin/env python3

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[2]
PLAYBOOK = (ROOT / "playbooks/agents/hermes-lcm-backfill.yml").read_text()
SERVICE = (ROOT / "templates/hermes/hermes-lcm-backfill.service.j2").read_text()
TIMER = (ROOT / "templates/hermes/hermes-lcm-backfill.timer.j2").read_text()
VARS = (ROOT / "inventory/group_vars/hermes_hosts/vars.yml").read_text()


class HermesLcmBackfillTests(unittest.TestCase):
    def test_mutation_requires_exact_approval(self) -> None:
        self.assertIn("hermes_lcm_backfill_mode != 'apply'", PLAYBOOK)
        self.assertIn("hermes_lcm_backfill_approved | bool", PLAYBOOK)
        self.assertIn("enable-native-hermes-lcm-background-backfill", VARS)

    def test_backfill_is_bounded_and_uses_profile_owned_native_config(self) -> None:
        self.assertIn("hermes_lcm_backfill_batch: 16", VARS)
        self.assertIn("hermes_lcm_backfill_passes_per_run: 8", VARS)
        self.assertIn("hermes_lcm_backfill_uncertain_retry_batch: 1", VARS)
        self.assertIn("hermes_lcm_backfill_uncertain_retry_max_passes: 128", VARS)
        self.assertIn("backfill-bounded", SERVICE)
        self.assertIn(
            "EnvironmentFile={{ hermes_lcm_backfill_profile.home }}/lcm.env",
            SERVICE,
        )
        self.assertIn(
            "ConditionPathExists={{ hermes_lcm_backfill_profile.home }}/lcm.env",
            SERVICE,
        )
        self.assertNotIn("LCM_EMBEDDING_PROVIDER=", SERVICE)
        self.assertNotIn("LCM_EMBEDDING_MODEL=", SERVICE)
        self.assertNotIn("LCM_OLLAMA_BASE_URL=", SERVICE)
        self.assertNotIn("hermes_lcm_embedding_provider", VARS)
        self.assertIn("Deploy bounded LCM backfill runner", PLAYBOOK)
        self.assertNotIn("OPENAI_API_KEY", SERVICE)
        self.assertNotIn("GEMINI_API_KEY", SERVICE)
        self.assertNotIn("OPENROUTER_API_KEY", SERVICE)

    def test_local_uncertainty_recovery_precedes_normal_backfill(self) -> None:
        preflight = SERVICE.index("ExecStartPre=")
        normal = SERVICE.index("ExecStart=")
        self.assertLess(preflight, normal)
        self.assertIn("--retry-uncertain", SERVICE[preflight:normal])
        self.assertIn(
            "--limit {{ hermes_lcm_backfill_uncertain_retry_batch }}",
            SERVICE[preflight:normal],
        )
        self.assertIn(
            "--max-passes {{ hermes_lcm_backfill_uncertain_retry_max_passes }}",
            SERVICE[preflight:normal],
        )
        self.assertNotIn("--retry-uncertain", SERVICE[normal:])
        self.assertIn(
            "--limit {{ hermes_lcm_backfill_batch }}",
            SERVICE[normal:],
        )
        self.assertIn("--approved --confirmation", SERVICE[preflight:normal])

    def test_summary_and_chunk_lanes_are_staggered(self) -> None:
        self.assertIn("corpus: summary", VARS)
        self.assertIn("corpus: chunks", VARS)
        self.assertIn("initial_delay: 20m", VARS)
        self.assertIn("initial_delay: 35m", VARS)
        self.assertIn("OnActiveSec=", TIMER)
        self.assertNotIn("OnBootSec=", TIMER)
        self.assertIn("OnUnitInactiveSec=", TIMER)

    def test_service_is_low_priority_and_hardened(self) -> None:
        for marker in (
            "Nice=10",
            "CPUWeight=20",
            "IOWeight=20",
            "NoNewPrivileges=true",
            "ProtectSystem=strict",
            "ReadWritePaths={{ hermes_lcm_backfill_profile.home }}",
        ):
            self.assertIn(marker, SERVICE)

    def test_backfill_never_restarts_a_gateway(self) -> None:
        self.assertNotIn("hermes-gateway", PLAYBOOK)
        self.assertNotIn("state: restarted", PLAYBOOK)
        self.assertIn("systemd-analyze", PLAYBOOK)
        self.assertIn("Stop check mode after complete LCM backfill preview", PLAYBOOK)


if __name__ == "__main__":
    unittest.main()
