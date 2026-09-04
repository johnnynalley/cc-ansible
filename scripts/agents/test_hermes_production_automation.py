#!/usr/bin/env python3
"""Structural acceptance tests for production Hermes automation."""

from __future__ import annotations

import json
import hashlib
import re
import unittest
from pathlib import Path

import yaml
from jinja2 import Environment, StrictUndefined


ROOT = Path(__file__).parents[2]


def render_manifest(path: Path, *, dedicated_rigel: bool) -> dict:
    source = path.read_text(encoding="utf-8")
    rendered = Environment(undefined=StrictUndefined).from_string(source).render(
        hermes_rigel_dedicated_discord_enabled=dedicated_rigel,
        hermes_automation_rigel_channel_id=(
            "{{ hermes_automation_rigel_channel_id }}"
        ),
        hermes_automation_logs_channel_id=(
            "{{ hermes_automation_logs_channel_id }}"
        ),
        hermes_automation_social_channel_id=(
            "{{ hermes_automation_social_channel_id }}"
        ),
        hermes_automation_owner_user_id=(
            "{{ hermes_automation_owner_user_id }}"
        ),
        hermes_astra_logs_channel_id="{{ hermes_astra_logs_channel_id }}",
        hermes_native_update_profile_home=(
            "{{ hermes_native_update_profile_home }}"
        ),
        hermes_rigel_discord_channel_id=(
            "{{ hermes_rigel_discord_channel_id }}"
        ),
    )
    return json.loads(rendered)


class ProductionAutomationTests(unittest.TestCase):
    def test_manifest_is_bounded_and_uses_fixed_delivery(self):
        source = (
            ROOT / "templates/hermes/astra-production-jobs.json.j2"
        ).read_text()
        value = render_manifest(
            ROOT / "templates/hermes/astra-production-jobs.json.j2",
            dedicated_rigel=False,
        )
        jobs = value["jobs"]
        self.assertEqual(value["schemaVersion"], 1)
        self.assertEqual(value["profile"], "astra")
        self.assertEqual(len(jobs), 18)
        self.assertEqual(len({job["key"] for job in jobs}), len(jobs))
        self.assertEqual(
            {job["deliver"] for job in jobs},
            {
                "discord:{{ hermes_automation_rigel_channel_id }}",
                "discord:{{ hermes_automation_logs_channel_id }}",
                "discord:{{ hermes_automation_social_channel_id }}",
                "local",
            },
        )
        self.assertIsNone(re.search(r"[0-9]{17,20}", source))
        self.assertIn("operational-heartbeat", {job["key"] for job in jobs})
        by_key = {job["key"]: job for job in jobs}
        self.assertIn("host_admin", by_key["operational-heartbeat"]["enabledToolsets"])
        self.assertIn("agent_docker", by_key["operational-heartbeat"]["enabledToolsets"])
        self.assertIn(
            "final response must be exactly [SILENT] and nothing else in every case",
            by_key["operational-heartbeat"]["prompt"],
        )
        self.assertIn(
            "Send any verified actionable finding only through the native Discord tool",
            by_key["operational-heartbeat"]["prompt"],
        )
        agent_jobs = [job for job in jobs if not job.get("noAgent")]
        self.assertTrue(agent_jobs)
        self.assertTrue(
            all(
                job.get("workdir") == "{{ hermes_native_update_profile_home }}"
                for job in agent_jobs
            )
        )
        daily = by_key["daily-summary"]
        self.assertEqual(
            daily["deliver"],
            "discord:{{ hermes_automation_logs_channel_id }}",
        )
        self.assertTrue(daily["continuity"])
        self.assertEqual(daily["skills"], ["daily-summary-thread"])
        self.assertEqual(
            daily["enabledToolsets"],
            ["terminal", "file", "discord", "discord_parity"],
        )
        for key in ("self-evolution-maintenance", "self-evolution-daily"):
            self.assertIn(key, by_key)
            self.assertNotIn("provider", by_key[key])
            self.assertNotIn("model", by_key[key])
            self.assertEqual(by_key[key]["skills"], ["self-evolution"])
            self.assertIn("native", by_key[key]["prompt"])
            self.assertIn("memories/USER.md", by_key[key]["prompt"])
            self.assertIn("memories/MEMORY.md", by_key[key]["prompt"])
            self.assertIn("workspaces/cc-ansible", by_key[key]["prompt"])
            self.assertIn("git -C", by_key[key]["prompt"])
            self.assertIn("Do not assume the sqlite3 CLI exists", by_key[key]["prompt"])
            self.assertNotIn("legacy-openclaw/workspace", by_key[key]["prompt"])
            self.assertIn("active discovery allowlist", by_key[key]["prompt"])
            self.assertIn("managed-data", by_key[key]["prompt"])
            self.assertIn("shared semantic-maintenance lease", by_key[key]["prompt"])
        self.assertNotIn("gpt-5.4-mini", source)
        fortnite = by_key["fortnite-progress"]["prompt"]
        self.assertIn("including valid zero-activity days", fortnite)
        self.assertIn("never return [SILENT] merely because deltas are zero", fortnite)
        self.assertIn("hardware-inventory", (
            ROOT / "files/hermes/profile-skills-contract.json"
        ).read_text())

    def test_dedicated_rigel_moves_only_the_academic_lane(self):
        astra = render_manifest(
            ROOT / "templates/hermes/astra-production-jobs.json.j2",
            dedicated_rigel=True,
        )
        rigel = render_manifest(
            ROOT / "templates/hermes/rigel-production-jobs.json.j2",
            dedicated_rigel=True,
        )
        self.assertEqual(len(astra["jobs"]), 17)
        self.assertNotIn(
            "rigel-academic-alerts", {job["key"] for job in astra["jobs"]}
        )
        self.assertEqual(
            [job["key"] for job in rigel["jobs"]],
            ["rigel-academic-alerts"],
        )
        self.assertEqual(
            rigel["jobs"][0]["deliver"],
            "discord:{{ hermes_rigel_discord_channel_id }}",
        )

    def test_every_current_and_historical_schedule_has_a_final_disposition(self):
        design = json.loads(
            (ROOT / "files/hermes/openclaw-parity-contract.json").read_text()
        )
        production = json.loads(
            (
                ROOT
                / "files/hermes/production-automation-reconciliation.json"
            ).read_text()
        )
        self.assertEqual(design["source"]["enabledCronCount"], 26)
        self.assertEqual(design["source"]["historicalEnabledCronCount"], 28)
        self.assertEqual(design["source"]["historicalOnlyCronCount"], 7)
        self.assertEqual(design["source"]["sharedCronCount"], 21)
        self.assertEqual(design["source"]["logicalHeartbeatCount"], 3)
        self.assertEqual(len(production["lanes"]), 29)
        self.assertEqual(len(production["historicalLanes"]), 7)
        self.assertEqual(production["source"]["totalActiveReconciledLanes"], 29)
        self.assertEqual(production["source"]["totalHistoricalReconciledLanes"], 7)
        self.assertEqual(production["production"]["nativeCronJobs"], 19)
        self.assertEqual(
            production["production"]["astraFallbackNativeCronJobs"], 18
        )
        self.assertEqual(
            production["production"]["astraDedicatedNativeCronJobs"], 17
        )
        self.assertEqual(production["production"]["dubbleNativeCronJobs"], 1)
        self.assertEqual(production["production"]["rigelNativeCronJobs"], 1)
        self.assertEqual(
            production["lanes"]["heartbeat-dubble"]["target"],
            "dubble-thread-followup",
        )
        self.assertEqual(
            production["lanes"]["9d8b09a6-6ea4-4154-813e-e751a12c88ea"]["target"],
            "hermes-retained-automation@daily-updates.service",
        )
        self.assertEqual(
            production["lanes"]["7bd30e8a-3ac0-465e-ad29-b79510224c4d"]["target"],
            "hermes-retained-automation@daily-media.service",
        )
        self.assertEqual(
            production["lanes"]["875ce2c3-df80-4391-9bef-ec158e521781"]["target"],
            "hermes-retained-automation@daily-personal.service",
        )
        self.assertEqual(
            production["lanes"]["c49330bb-7488-416b-91ba-15ba022f8023"]["target"],
            "hermes-retained-automation@daily-assemble.service",
        )
        self.assertEqual(
            production["lanes"]["b5d5840b-e4d9-4b24-9f41-e5f1690a29a9"][
                "target"
            ],
            "astra-self-evolution-maintenance",
        )
        self.assertEqual(
            production["historicalLanes"][
                "0a2ed1ee-91ee-4488-b5b7-93386cfb26e7"
            ]["disposition"],
            "preserved-historical",
        )
        self.assertEqual(
            {
                row["runtimeDisposition"]
                for row in production["historicalLanes"].values()
            },
            {"preserved-inactive"},
        )

    def test_playbook_has_approval_backup_health_and_rescue_gates(self):
        text = (ROOT / "playbooks/agents/hermes-automation.yml").read_text()
        vars_text = (
            ROOT / "inventory/group_vars/hermes_hosts/vars.yml"
        ).read_text()
        for required in (
            "hermes_automation_required_confirmation",
            "Require the OpenClaw scheduler and delivery path offline",
            "Create targeted pre-automation rollback directory",
            "Back up existing automation state directories",
            "Normalize existing native profile backup locks",
            "Create private native profile backup staging directories",
            "Preserve native profile backups in the rollback directory",
            "Require unique rollback paths inside approved roots",
            "Resolve the managed Hermes Python prerequisite",
            "Publish retained profile skill parity contract",
            "Publish mutable native bootstrap parity contract",
            "Resolve production Gateway mount namespaces",
            "Require live production Gateway processes",
            "Inspect subscription-backed primary model credentials",
            "Require native subscription-backed primary model credentials",
            "hermes_bootstrap_parity_validator_live",
            "hermes_bootstrap_parity_contract_live",
            "Stop and disable superseded collapsed Daily Summary timer",
            "Remove superseded collapsed Daily Summary timer",
            "Deploy exact native Gateway update sudoers bridge",
            "Inspect pre-transaction Hermes Gateway activity",
            "Record pre-transaction Hermes Gateway state",
            "Require an existing stopped maintenance window before deferred restart",
            "Create shared credential-free production manifest directory",
            "Deploy Astra production cron manifest",
            "Deploy Dubble production cron manifest",
            "Deploy Rigel production cron manifest",
            "Verify production cron manifests are readable by their profiles",
            "Remove superseded private production cron manifests",
            "Audit Astra native schedule declarations after convergence",
            "Audit Dubble native schedule declarations after convergence",
            "Audit Rigel native schedule declarations after convergence",
            "Report native schedule declaration differences without mutation",
            "Require every requested native schedule seed creation",
            "Require exact native schedule restoration when requested",
            "Require Health receiver continuity",
            "Mark the automation transaction successful",
            "Start Astra through the native systemd readiness window",
            "Start Dubble through the native systemd readiness window",
            "Start Rigel through the native systemd readiness window",
            "Inspect stopped Astra native cron state",
            "Inspect stopped Dubble native cron state",
            "Inspect stopped Rigel native cron state",
            "Stop available Hermes automation timers before restore",
            "Remove changed automation state directories before restore",
            "Restore backed-up automation state directories",
            "Exclude existing timers from the automation transaction",
            "Recheck native updater workers after timer exclusion",
            "Restore pre-transaction timer state",
            "Restore pre-transaction Hermes consumer state after failure",
            "Stop after read-only Hermes automation check-mode preflight",
        ):
            self.assertIn(required, text)
        for forbidden in (
            "managed-policy.sha256",
            "hermes-managed-config.yaml.j2",
            "/etc/hermes/astra/config.yaml",
            "/etc/hermes/dubble/config.yaml",
            "/etc/hermes/rigel/config.yaml",
            "/etc/hermes/astra/skills",
            "/etc/hermes/dubble/skills",
            "/etc/hermes/rigel/skills",
            "Publish reviewed managed Hermes profile skills",
            "Migrate isolated profile configs through native Hermes",
        ):
            self.assertNotIn(forbidden, text)
        self.assertEqual(
            text.count('group: "{{ hermes_runtime_readers_group }}"'),
            5,
        )
        self.assertEqual(
            text.count("reconcile_precheck.rc not in [0, 3]"),
            3,
        )
        self.assertIn("hermes_automation_schedule_mode: preserve", vars_text)
        self.assertIn("--seed", text)
        self.assertIn("--restore", text)
        self.assertIn("--audit", text)
        self.assertLess(
            text.index(
                "Decide which native schedules require explicit reconciliation"
            ),
            text.index("Decide which production consumers need one restart"),
        )
        self.assertIn(
            "when: hermes_automation_schedule_mode == 'restore'",
            text,
        )
        self.assertIn("/usr/sbin/runuser", text)
        self.assertIn("auth\n          - list", text)
        self.assertIn("do not substitute a metered API key", text)
        self.assertIn(
            "not (hermes_automation_transaction_succeeded | default(false) | bool)",
            text,
        )
        self.assertIn("/usr/bin/head", text)
        self.assertIn("--bytes=0", text)
        self.assertIn('"HERMES_HOME={{ item.home }}"', text)
        self.assertNotIn('become_user: "{{ item.user }}"', text)
        self.assertIn("map(attribute='account_home')", text)
        self.assertIn("/.hermes/.backup.lock", text)
        unit = (
            ROOT / "templates/hermes/hermes-profile-backup@.service.j2"
        ).read_text()
        self.assertIn(
            "/var/lib/hermes/%i/.hermes/.backup.lock", unit
        )
        self.assertIn("hermes_automation_defer_gateway_restart", text)
        self.assertIn("rejectattr('active', 'equalto', 'inactive')", text)
        self.assertGreaterEqual(
            text.count("not hermes_automation_defer_gateway_restart | bool"),
            12,
        )
        self.assertIn("ansible.builtin.template", text)
        self.assertIn("templates/hermes", text)
        self.assertNotIn("\n              - start\n              - --system", text)
        self.assertIn(
            "hermes_automation_dubble_stopped_cron.stat.exists",
            text,
        )
        self.assertIn(
            "hermes_automation_rigel_stopped_cron.stat.exists",
            text,
        )
        self.assertIn(
            "/etc/hermes/astra/production-automation-reconciliation.json",
            text,
        )
        self.assertIn("hermes_astra_calendar_live_root,", text)
        self.assertIn("item.name not in hermes_automation_retired_timers", text)
        self.assertIn("astraFallbackNativeCronJobs", text)
        self.assertIn("astraDedicatedNativeCronJobs", text)
        self.assertNotIn(".astraNativeCronJobs", text)

    def test_shared_reconciliation_contract_is_not_astra_private(self):
        variables = yaml.safe_load(
            (ROOT / "inventory/group_vars/hermes_hosts/vars.yml").read_text()
        )
        self.assertEqual(
            variables["hermes_automation_reconciliation_live"],
            "/etc/hermes/production-jobs/reconciliation.json",
        )
        self.assertFalse(variables["hermes_automation_defer_gateway_restart"])

    def test_dedicated_rigel_environment_includes_owner_authorization(self):
        text = (ROOT / "playbooks/agents/hermes-automation.yml").read_text()
        task = text.split(
            "Enroll the complete dedicated Rigel Discord environment", 1
        )[1].split("Record the three-consumer private Discord enrollment", 1)[0]
        for key in (
            "DISCORD_BOT_TOKEN",
            "DISCORD_ALLOWED_USERS",
            "DISCORD_HOME_CHANNEL",
            "DISCORD_HOME_CHANNEL_NAME",
        ):
            self.assertIn(f"key: {key}", task)
        self.assertIn("hermes_automation_owner_user_id", task)
        self.assertIn("hermes_rigel_discord_channel_id", task)
        self.assertIn("group: root", task)
        self.assertIn('mode: "0400"', task)
        self.assertIn("no_log: true", task)

    def test_native_update_exception_remains_exactly_scoped(self):
        text = (ROOT / "templates/hermes/hermes-native-update.service.j2").read_text()
        transaction = (
            ROOT / "scripts/agents/hermes-native-update-transaction.py"
        ).read_text()
        contract = (
            ROOT / "templates/hermes/hermes-native-update-transaction.json.j2"
        ).read_text()
        variables = yaml.safe_load(
            (ROOT / "inventory/group_vars/hermes_hosts/vars.yml").read_text()
        )
        self.assertIn("NoNewPrivileges=true", text)
        self.assertNotIn("/usr/bin/sudo", text)
        self.assertIn("hermes_native_update_transaction_live", text)
        self.assertIn("ExecStart=/usr/bin/python3", text)
        self.assertNotIn("ExecStartPost=", text)
        self.assertNotIn("RestrictSUIDSGID=true", text)
        self.assertIn("CapabilityBoundingSet=\n", text)
        self.assertNotIn("CAP_DAC", text)
        self.assertNotIn("CAP_CHOWN", text)
        self.assertIn("AmbientCapabilities=", text)
        self.assertIn('"/usr/bin/systemd-run"', transaction)
        self.assertIn('f"--uid={account.pw_name}"', transaction)
        self.assertIn('"--property=CapabilityBoundingSet="', transaction)
        self.assertIn('"--property=AmbientCapabilities="', transaction)
        self.assertEqual(
            variables["hermes_native_update_gateway_wait_seconds"], 120
        )
        self.assertIn('"update",', transaction)
        self.assertIn("--yes", transaction)
        self.assertIn('"--backup"', transaction)
        self.assertIn('"--branch"', transaction)
        self.assertIn('"--switch-branch"', transaction)
        self.assertNotIn("hermes_mem0_stable_dependencies", contract)
        self.assertNotIn('"pip", "install"', transaction)
        self.assertNotIn("hermes_mem0_gemini_dependency", contract)
        self.assertNotIn("memoryDependencyUpdater", contract)
        self.assertIn("restore_active_profiles", transaction)

    def test_public_fetch_uses_standalone_driver_without_privilege_exception(self):
        fetch = (
            ROOT / "templates/hermes/hermes-fortnite-calendar-fetch.service.j2"
        ).read_text()
        apply = (
            ROOT / "templates/hermes/hermes-fortnite-calendar.service.j2"
        ).read_text()
        variables = yaml.safe_load(
            (ROOT / "inventory/group_vars/hermes_hosts/vars.yml").read_text()
        )
        self.assertIn("User=hermes-astra", fetch)
        self.assertIn("NoNewPrivileges=true", fetch)
        self.assertIn("RestrictSUIDSGID=true", fetch)
        self.assertIn("CapabilityBoundingSet=\n", fetch)
        self.assertNotIn("CAP_SYS_ADMIN", fetch)
        self.assertIn("PYTHONNOUSERSITE=1", fetch)
        self.assertIn("hermes_fortnite_calendar_fetch_live", fetch)
        self.assertIn("--geckodriver", fetch)
        self.assertIn("--firefox-binary", fetch)
        self.assertNotIn("/snap/bin/geckodriver", fetch)
        self.assertEqual(variables["hermes_fortnite_geckodriver_version"], "0.37.1")
        self.assertRegex(
            variables["hermes_fortnite_geckodriver_sha256"], r"^[0-9a-f]{64}$"
        )
        self.assertEqual(
            variables["hermes_fortnite_firefox_binary_path"],
            "/snap/firefox/current/usr/lib/firefox/firefox",
        )
        self.assertNotIn("legacy_workspace", fetch)
        self.assertNotIn("source_env", fetch)
        self.assertIn("NoNewPrivileges=true", apply)
        self.assertIn("hermes-fortnite-calendar-fetch.service", apply)
        self.assertIn("--schedule-file", apply)

    def test_daily_summary_collector_can_read_its_real_inputs(self):
        text = (
            ROOT / "templates/hermes/hermes-retained-automation@.service.j2"
        ).read_text()
        for path in (
            "hermes_astra_calendar_live_root",
            "HERMES_HEALTH_REPORT_JSON",
            "HERMES_HEALTH_REPORT_MARKDOWN",
            "hermes_health_receiver_report_dir",
        ):
            self.assertIn(path, text)
        self.assertIn("InaccessiblePaths={{ hermes_health_receiver_db }}", text)
        self.assertNotIn("HERMES_HEALTH_DB=", text)
        self.assertNotIn("HERMES_HEALTH_SUMMARY=", text)
        self.assertIn("Environment=HOME=/var/lib/hermes/astra", text)
        self.assertIn("EnvironmentFile=", text)
        self.assertIn("hermes_automation_native_workspace", text)
        self.assertNotIn("legacy_workspace", text)
        self.assertNotIn("/home/johnny/.openclaw", text)
        self.assertNotIn("/.ssh/known_hosts", text)
        self.assertNotIn("/.ssh/id_ed25519", text)
        self.assertIn("Environment=HERMES_HOME=", text)
        self.assertIn("Environment=HERMES_MANAGED_DIR=/etc/hermes/astra", text)

    def test_active_profile_and_collectors_never_use_openclaw_runtime_paths(self):
        paths = (
            ROOT / "templates/hermes/hermes-retained-automation@.service.j2",
            ROOT / "templates/hermes/hermes-fortnite-calendar.service.j2",
            ROOT / "templates/hermes/hermes-warframe-feed.service.j2",
        )
        for path in paths:
            text = path.read_text()
            self.assertNotIn("legacy-openclaw", text, str(path))
            self.assertNotIn("/home/johnny/.openclaw", text, str(path))

    def test_daily_summary_source_lanes_keep_openclaw_cadence(self):
        expected = {
            "hermes-daily-updates-collect.timer.j2": (
                "06:15:00",
                "hermes-retained-automation@daily-updates.service",
            ),
            "hermes-daily-media-collect.timer.j2": (
                "06:30:00",
                "hermes-retained-automation@daily-media.service",
            ),
            "hermes-daily-personal-collect.timer.j2": (
                "06:45:00",
                "hermes-retained-automation@daily-personal.service",
            ),
            "hermes-daily-summary-assemble.timer.j2": (
                "07:00:00",
                "hermes-retained-automation@daily-assemble.service",
            ),
        }
        for filename, (clock, unit) in expected.items():
            text = (ROOT / "templates/hermes" / filename).read_text()
            self.assertIn(f"OnCalendar=*-*-* {clock} America/Chicago", text)
            self.assertIn(f"Unit={unit}", text)
            self.assertNotIn("RandomizedDelaySec", text)
        variables = yaml.safe_load(
            (ROOT / "inventory/group_vars/hermes_hosts/vars.yml").read_text()
        )
        self.assertEqual(
            variables["hermes_automation_retired_timers"],
            ["hermes-daily-summary-collect.timer"],
        )
        retained = (
            ROOT / "scripts/agents/hermes-retained-automation.py"
        ).read_text()
        for task in ("daily-updates", "daily-media", "daily-personal", "daily-assemble"):
            self.assertIn(f'"{task}"', retained)
        self.assertNotIn('"daily-summary", "fortnite-progress"', retained)
        self.assertIn(
            'scratch = output_root / f".daily-summary.{os.getpid()}.md"',
            retained,
        )
        self.assertIn("atomic_text(destination, content)", retained)
        summary_input = (
            ROOT / "scripts/agents/hermes-daily-summary-input.py"
        ).read_text()
        self.assertIn("MAX_AGE_SECONDS = 15 * 60", summary_input)

    def test_freshrss_is_a_daily_summary_input_not_a_publisher(self):
        manifest = render_manifest(
            ROOT / "templates/hermes/astra-production-jobs.json.j2",
            dedicated_rigel=False,
        )
        self.assertNotIn(
            "freshrss-daily-briefing",
            {job["key"] for job in manifest["jobs"]},
        )
        retained = (
            ROOT / "scripts/agents/hermes-retained-automation.py"
        ).read_text()
        self.assertIn("/usr/local/libexec/hermes-freshrss-collect", retained)
        self.assertIn("daily-summary-sections/rss.md", retained)
        helper = (
            ROOT / "scripts/agents/hermes-freshrss-briefing.py"
        ).read_text()
        self.assertIn("## RSS Candidates", helper)
        self.assertNotIn("hermes_cron_delivery", helper)
        self.assertNotIn("print(text)", helper)
        unit = (
            ROOT / "templates/hermes/hermes-retained-automation@.service.j2"
        ).read_text()
        self.assertIn("hermes_astra_freshrss_live_root", unit)

    def test_astra_has_native_providers_with_private_credential_rollout(self):
        playbook = (ROOT / "playbooks/agents/hermes-automation.yml").read_text()
        self.assertIn(
            "Read native Astra provider credentials privately", playbook
        )
        self.assertIn(
            "Enroll Astra provider credentials and compatibility aliases", playbook
        )
        self.assertIn(
            "Enroll subscription fallback credentials for every profile", playbook
        )
        self.assertIn("Remove retired Anthropic provider credentials", playbook)
        self.assertIn(
            "Remove inactive metered API credentials from Hermes profiles", playbook
        )
        self.assertIn("^ANTHROPIC_API_KEY=", playbook)
        self.assertIn("state: absent", playbook)
        self.assertIn("'/etc/hermes/astra/.env'", playbook)
        self.assertIn("hermes_automation_astra_provider_environment.changed", playbook)
        for name in (
            "OLLAMA_API_KEY",
            "EBAY_APP_ID",
            "EBAY_CERT_ID",
            "ICLOUD_APP_PASSWORD",
            "NEXTCLOUD_CALDAV_APP_PASSWORD",
        ):
            self.assertIn(name, playbook)
        for name in (
            "GEMINI_API_KEY",
            "GOOGLE_API_KEY",
            "OPENROUTER_API_KEY",
            "OPENAI_API_KEY",
        ):
            self.assertIn(name, playbook)
            self.assertNotIn(f"source: {name}", playbook)
        self.assertIn("Require native Fortnite collector credentials", playbook)
        self.assertNotIn("hermes_openclaw_source_env", playbook)
        self.assertNotIn("/home/johnny/.openclaw/.env", playbook)

    def test_astra_calendar_and_mail_are_native_service_identity_tools(self):
        playbook = (ROOT / "playbooks/agents/hermes-automation.yml").read_text()
        for required in (
            "Create Astra native calendar and mail config directories",
            "Normalize imported Astra calendar cache ownership",
            "Convert imported Astra vdirsyncer collection paths",
            "Verify imported Astra vdirsyncer collection paths",
            "Inspect one-time OpenClaw Fortnite calendar ledger migration",
            "Reset only the stale imported Fortnite calendar sync ledger",
            "Record successful OpenClaw Fortnite calendar ledger migration",
            "Deploy Astra native calendar and mail configs",
            "Sync Astra's native CalDAV cache as its service identity",
            "Verify Astra can read its current calendar",
            "Verify Astra can read one iCloud envelope natively",
        ):
            self.assertIn(required, playbook)
        self.assertIn("/usr/sbin/runuser", playbook)
        self.assertIn("HOME=/var/lib/hermes/astra", playbook)
        self.assertIn("status/personal.collections", playbook)
        self.assertIn("hermes_vdirsyncer_state_migrator_live", playbook)
        self.assertIn("stdin_add_newline: false", playbook)
        self.assertNotIn("openclaw-get-caldav-password", playbook)
        self.assertEqual(
            playbook.count("Sync Astra's native CalDAV cache as its service identity"),
            1,
        )
        self.assertLess(
            playbook.index("Sync Astra's native CalDAV cache as its service identity"),
            playbook.index("Stop Astra natively once when cron or runtime state changed"),
        )

        vdirsyncer = (
            ROOT / "templates/hermes/astra-vdirsyncer-config.j2"
        ).read_text()
        himalaya = (
            ROOT / "templates/hermes/astra-himalaya-config.toml.j2"
        ).read_text()
        self.assertIn("/etc/hermes/astra/.env", vdirsyncer)
        self.assertIn("NEXTCLOUD_CALDAV_APP_PASSWORD", vdirsyncer)
        self.assertIn("/etc/hermes/astra/.env", himalaya)
        self.assertIn("ICLOUD_APP_PASSWORD", himalaya)
        self.assertNotIn("/home/johnny", vdirsyncer + himalaya)

    def test_gateways_do_not_enforce_exact_native_schedule_manifests(self):
        playbook = (ROOT / "playbooks/agents/hermes-automation.yml").read_text()
        base = (
            ROOT / "templates/hermes/hermes-gateway-hardening.conf.j2"
        ).read_text()
        dropin = (
            ROOT
            / "templates/hermes/hermes-gateway-astra-automation.conf.j2"
        ).read_text()
        rigel = (
            ROOT
            / "templates/hermes/hermes-gateway-rigel-automation.conf.j2"
        ).read_text()
        self.assertNotIn("hermes_automation_audit_live", base)
        for rendered in (dropin, rigel):
            self.assertNotIn("hermes_cron_reconcile_live", rendered)
            self.assertNotIn("hermes_openclaw_parity_validator_live", rendered)
        self.assertIn("hermes_automation_readers_group", dropin)
        self.assertIn("hermes_automation_readers_group", rigel)
        self.assertEqual(
            list((ROOT / "templates/hermes").glob("*dubble*automation*")),
            [],
        )
        self.assertIn("Remove obsolete Dubble automation parity gate", playbook)
        self.assertIn(
            "Remove superseded native-migration startup drop-in",
            playbook,
        )
        self.assertIn("20-automation.conf", playbook)

    def test_rigel_private_environment_metadata_is_consistent(self):
        playbook = (ROOT / "playbooks/agents/hermes-automation.yml").read_text()
        self.assertGreaterEqual(
            playbook.count("'0400' if item.profile == 'rigel' else '0440'"),
            1,
        )
        self.assertGreaterEqual(
            playbook.count("'0400' if item == 'rigel' else '0440'"),
            1,
        )
        self.assertGreaterEqual(
            playbook.count("'0400' if item.0 == 'rigel' else '0440'"),
            1,
        )
        self.assertGreaterEqual(
            playbook.count("'root' if item == 'rigel' else 'hermes-' ~ item"),
            1,
        )
        self.assertGreaterEqual(
            playbook.count(
                "'root' if item.0 == 'rigel' else 'hermes-' ~ item.0"
            ),
            1,
        )

    def test_retained_collector_runs_as_astra_without_source_writes(self):
        text = (
            ROOT / "templates/hermes/hermes-retained-automation@.service.j2"
        ).read_text()
        self.assertIn("User=hermes-astra", text)
        self.assertIn("Group=hermes-astra", text)
        self.assertIn("Environment=HOME=/var/lib/hermes/astra", text)
        self.assertIn("ProtectHome=tmpfs", text)
        self.assertIn(
            "WorkingDirectory={{ hermes_automation_native_workspace }}",
            text,
        )
        self.assertIn(
            "HERMES_AUTOMATION_WORKSPACE={{ hermes_automation_native_workspace }}",
            text,
        )
        self.assertIn(
            "{{ hermes_profile_data_root }}/astra/writable/data/fortnite-progress",
            text,
        )
        self.assertIn(
            "{{ hermes_automation_output_root }}/daily-summary-sections:",
            text,
        )
        self.assertNotIn(
            "hermes_automation_legacy_workspace", text
        )
        self.assertNotIn("/home/johnny/.openclaw", text)
        self.assertNotIn("/.ssh/id_ed25519", text)
        self.assertNotIn("ProtectHome=read-only", text)

    def test_media_collector_is_repo_managed_and_uses_astra_ssh(self):
        playbook = (ROOT / "playbooks/agents/hermes-automation.yml").read_text()
        variables = yaml.safe_load(
            (ROOT / "inventory/group_vars/hermes_hosts/vars.yml").read_text()
        )
        retained = (
            ROOT / "scripts/agents/hermes-retained-automation.py"
        ).read_text()
        updates = (
            ROOT / "scripts/agents/hermes-daily-updates-collect.py"
        ).read_text()
        self.assertEqual(
            variables["hermes_retained_media_source"],
            "scripts/agents/hermes-media-summary-collect.py",
        )
        source = Path(variables["hermes_retained_media_source"]).read_text()
        self.assertEqual(source.count("SSH_USER = 'hermes-astra'"), 1)
        self.assertNotIn("/home/johnny/.openclaw", source)
        self.assertIn("Deploy root-owned automation helpers", playbook)
        self.assertIn("Deploy the least-privilege retained collector environment", playbook)
        self.assertIn("hermes-media-summary-collect", retained)
        self.assertNotIn('"dbc@', updates)
        self.assertNotIn('"johnny@', updates)
        heartbeat = (
            ROOT
            / "files/hermes/profile-skills/astra/operational-heartbeat/SKILL.md"
        ).read_text()
        self.assertNotIn("ssh dbc@", heartbeat)
        self.assertNotIn("ssh johnny@", heartbeat)
        self.assertNotIn("sudo -n", heartbeat)
        self.assertNotIn("`ssh ", heartbeat)
        self.assertIn("`host_admin_hosts`", heartbeat)
        self.assertIn("`host_admin_request`", heartbeat)
        self.assertIn("`docker_inventory`", heartbeat)
        for probe in (
            "media-stack",
            "stream-relay",
            "storage-status",
            "media-storage-view",
            "plex-local",
            "nextcloud-local",
            "plex-corrupt-media",
        ):
            self.assertIn(f"`{probe}`", heartbeat)
        self.assertIn("at most one eligible due", heartbeat)
        self.assertIn("oldest `lastAttemptAt`", heartbeat)
        self.assertIn("must not prevent another due", heartbeat)
        self.assertIn("`lastAttemptAt` before the probe starts", heartbeat)
        self.assertIn("Persist the selected transition", heartbeat)
        self.assertIn("send first and then search Discord", heartbeat)
        self.assertIn("unknownProvenanceRoutes", heartbeat)
        self.assertIn("never proof of metered usage", heartbeat)
        self.assertNotIn("Read `state/remote-access.json`", heartbeat)
        self.assertIn("--maintenance-lease acquire --lease-owner heartbeat", heartbeat)
        self.assertIn("leave all nonsemantic heartbeat lanes", heartbeat)
        self.assertIn("## Unattended Execution Contract", heartbeat)
        self.assertIn("## Scheduled Final Response Contract", heartbeat)
        self.assertIn(
            "For every scheduled invocation, the final response is exactly `[SILENT]`",
            heartbeat,
        )
        self.assertIn("Never request interactive command", heartbeat)
        self.assertIn("Never call `execute_code`", heartbeat)
        self.assertIn("Never return an internal verification summary", heartbeat)
        self.assertIn("normal operating constraints, not checks", heartbeat)
        self.assertIn("Never claim failure", heartbeat)
        self.assertIn("missing optional extra verification", heartbeat)

    def test_private_calendar_collectors_run_as_astra(self):
        for name in (
            "hermes-warframe-feed.service.j2",
            "hermes-fortnite-calendar.service.j2",
        ):
            text = (ROOT / "templates" / "hermes" / name).read_text()
            self.assertIn("User=hermes-astra", text, name)
            self.assertIn("Group=hermes-astra", text, name)
            self.assertIn("Environment=HOME=/var/lib/hermes/astra", text, name)
            self.assertNotIn("BindPaths=-/home/", text, name)

        public_fetch = (
            ROOT
            / "templates/hermes/hermes-fortnite-calendar-fetch.service.j2"
        ).read_text()
        self.assertIn("User=hermes-astra", public_fetch)

    def test_convergence_does_not_execute_user_workflows(self):
        text = (ROOT / "playbooks/agents/hermes-automation.yml").read_text()
        for forbidden in (
            "Run retained Daily Summary collection once",
            "Run retained Fortnite progress collection once",
            "Run verified Warframe feed collection once",
            "Run validated Fortnite calendar transaction once",
            "retained-automation-state.tar.gz",
        ):
            self.assertNotIn(forbidden, text)

    def test_automation_transactions_its_config_validator_dependency(self):
        text = (ROOT / "playbooks/agents/hermes-automation.yml").read_text()
        self.assertGreaterEqual(
            text.count("hermes_docker_inventory_validator_live"), 2
        )
        self.assertIn("hermes_docker_inventory_validator_source", text)

    def test_rescue_is_not_best_effort(self):
        text = (ROOT / "playbooks/agents/hermes-automation.yml").read_text()
        rescue = text.split("      rescue:", 1)[1]
        self.assertNotIn("failed_when: false", rescue)

    def test_all_user_home_collectors_use_explicit_bind_allowlists(self):
        for name in (
            "hermes-retained-automation@.service.j2",
            "hermes-warframe-feed.service.j2",
            "hermes-fortnite-calendar.service.j2",
        ):
            text = (ROOT / "templates" / "hermes" / name).read_text()
            self.assertIn("ProtectHome=tmpfs", text, name)
            self.assertNotIn("ProtectHome=read-only", text, name)

        public_fetch = (
            ROOT / "templates/hermes/hermes-fortnite-calendar-fetch.service.j2"
        ).read_text()
        self.assertIn("ProtectHome=true", public_fetch)
        self.assertNotIn("BindPaths=-/home/", public_fetch)

    def test_unsafe_legacy_update_collector_is_not_invoked(self):
        text = (ROOT / "scripts/agents/hermes-retained-automation.py").read_text()
        self.assertNotIn("daily_updates_collect.py", text)
        self.assertNotIn("shell=True", text)
        self.assertIn("/usr/local/libexec/hermes-daily-updates-collect", text)
        replacement = (
            ROOT / "scripts/agents/hermes-daily-updates-collect.py"
        ).read_text()
        self.assertNotIn("shell=True", replacement)
        self.assertNotIn("openclaw", replacement.casefold())
        self.assertIn("NousResearch/hermes-agent", replacement)
        self.assertIn("PRIORITY = [", replacement)
        self.assertIn("REPOS = {", replacement)
        self.assertIn("Currently behind latest", replacement)
        self.assertIn("Recent upstream themes", replacement)
        self.assertIn("Hermes plugins and skills", replacement)
        self.assertIn("Security updates flagged on", replacement)
        self.assertIn('"ts440", "/usr/local/bin/storage-status"', replacement)

    def test_thread_archive_uses_native_cron_and_bounded_plugin(self):
        playbook = (ROOT / "playbooks/agents/hermes-automation.yml").read_text()
        variables = (ROOT / "inventory/group_vars/hermes_hosts/vars.yml").read_text()
        manifest = (
            ROOT / "templates/hermes/astra-production-jobs.json.j2"
        ).read_text()
        self.assertIn("astra-logs-thread-archive", manifest)
        self.assertIn('"discord_parity"', manifest)
        self.assertNotIn("discord-thread-archive.py", playbook)
        self.assertNotIn("discord_thread_archive", variables)
        self.assertNotIn("message queue", playbook.casefold())


if __name__ == "__main__":
    unittest.main()
