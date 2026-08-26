from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[2]
PLAYBOOK = (ROOT / "playbooks/agents/hermes-memory-servers.yml").read_text()
VARS = (ROOT / "inventory/group_vars/hermes_hosts/vars.yml").read_text()
UNIT = (ROOT / "templates/hermes/hermes-ollama.service.j2").read_text()


class HermesMemoryServersTests(unittest.TestCase):
    def test_mutation_requires_exact_approval(self) -> None:
        self.assertIn("hermes_memory_servers_mode != 'apply'", PLAYBOOK)
        self.assertIn("hermes_memory_servers_approved | bool", PLAYBOOK)
        self.assertIn("hermes_memory_servers_required_confirmation", PLAYBOOK)
        self.assertIn("upgrade-hermes-memory-servers-to-latest-stable", VARS)

    def test_only_official_stable_release_metadata_is_accepted(self) -> None:
        self.assertIn("api.github.com/repos/qdrant/qdrant/releases/latest", VARS)
        self.assertIn("api.github.com/repos/ollama/ollama/releases/latest", VARS)
        self.assertGreaterEqual(PLAYBOOK.count("prerelease | bool"), 2)
        self.assertGreaterEqual(PLAYBOOK.count("draft | bool"), 2)
        self.assertIn("^sha256:[0-9a-f]{64}$", PLAYBOOK)
        self.assertNotIn("-rc", VARS.lower())

    def test_backup_precedes_runtime_interruption(self) -> None:
        backup = PLAYBOOK.index("Create full single-node Qdrant snapshot")
        download = PLAYBOOK.index("Download full Qdrant snapshot")
        marker = PLAYBOOK.index("Prepare planned-stop markers for active memory consumers")
        stop = PLAYBOOK.index("Stop active consumers for one memory-server replacement window")
        self.assertLess(backup, download)
        self.assertLess(download, marker)
        self.assertLess(download, stop)
        self.assertLess(marker, stop)
        self.assertIn("hermes_memory_servers_rollback_root", PLAYBOOK)

    def test_ollama_capacity_bound_tracks_runtime_and_offloads_archive(self) -> None:
        self.assertIn("Measure installed Ollama runtime footprint", PLAYBOOK)
        self.assertIn("hermes_memory_servers_ollama_staging_required_bytes", PLAYBOOK)
        self.assertIn("* 5 // 4", PLAYBOOK)
        self.assertIn("+ 1073741824", PLAYBOOK)
        self.assertNotIn("first | int > 10737418240", PLAYBOOK)
        self.assertIn(
            "hermes_memory_servers_rollback_dir }}/ollama-{{ hermes_memory_servers_ollama_latest }}.tar.zst",
            PLAYBOOK,
        )
        self.assertIn("Report accepted local Ollama staging capacity", PLAYBOOK)
        self.assertIn("Stop after accepted memory-server transaction dry run", PLAYBOOK)
        self.assertIn("when: ansible_check_mode", PLAYBOOK)

    def test_zero_drift_apply_requires_versions_and_service_current(self) -> None:
        stop = PLAYBOOK.index(
            "Stop apply mode when backing servers and service are already current"
        )
        transaction = PLAYBOOK.index("Build memory-server transaction coordinates")
        self.assertLess(stop, transaction)
        self.assertIn(
            "hermes_memory_servers_qdrant_current == hermes_memory_servers_qdrant_latest",
            PLAYBOOK,
        )
        self.assertIn(
            "hermes_memory_servers_ollama_current == hermes_memory_servers_ollama_latest",
            PLAYBOOK,
        )
        self.assertIn("hermes_memory_servers_ollama_service_current | bool", PLAYBOOK)

    def test_context_only_drift_has_verified_rollback_and_no_gateway_restart(self) -> None:
        for marker in (
            "Back up prior Ollama service before configuration change",
            "Require exact Ollama configuration rollback copy",
            "Deploy managed Ollama context configuration",
            "Require managed context and uninterrupted consumer Gateways",
            "Restore prior Ollama service after context-only failure",
        ):
            self.assertIn(marker, PLAYBOOK)
        context_start = PLAYBOOK.index(
            "Converge Ollama service configuration without replacing servers"
        )
        context_end = PLAYBOOK.index(
            "Stop after accepted configuration-only convergence"
        )
        context_transaction = PLAYBOOK[context_start:context_end]
        self.assertNotIn("hermes-gateway-astra.service\n            state: restarted", context_transaction)
        self.assertNotIn("Pull newest stable Qdrant image", context_transaction)

    def test_managed_context_is_probed_through_live_ollama(self) -> None:
        self.assertIn("hermes_memory_servers_ollama_context_length: 16384", VARS)
        self.assertIn("OLLAMA_CONTEXT_LENGTH={{ hermes_memory_servers_ollama_context_length }}", UNIT)
        self.assertIn("/api/embed", PLAYBOOK)
        self.assertIn("/api/ps", PLAYBOOK)
        self.assertIn("map(attribute='context_length')", PLAYBOOK)
        self.assertGreaterEqual(PLAYBOOK.count("not ansible_check_mode"), 9)

    def test_dry_run_executes_only_required_read_only_preflight(self) -> None:
        config = PLAYBOOK.index(
            "Converge Ollama service configuration without replacing servers"
        )
        preflight = PLAYBOOK[:config]
        self.assertGreaterEqual(preflight.count("check_mode: false"), 11)
        post_config = PLAYBOOK[config:]
        self.assertEqual(post_config.count("check_mode: false"), 1)
        footprint = post_config.index("Measure installed Ollama runtime footprint")
        capacity = post_config.index(
            "Derive conservative local Ollama staging requirement"
        )
        self.assertIn("check_mode: false", post_config[footprint:capacity])

    def test_acceptance_covers_data_models_schema_and_real_providers(self) -> None:
        for marker in (
            "Require lossless Qdrant server update",
            "unchanged model inventory",
            "Require approved local embedding shape",
            "Require native v3 dense and BM25 schemas",
            "Validate each isolated Mem0 provider after backing-server updates",
            "Record accepted full memory-server stable update",
        ):
            self.assertIn(marker, PLAYBOOK)
        self.assertIn("isolated_mem0_provider_validation", PLAYBOOK)
        self.assertIn("ollama_archive_digest", PLAYBOOK)

    def test_rescue_restores_both_servers_and_all_consumers(self) -> None:
        for marker in (
            "Restore prior Ollama binary",
            "Restore prior Ollama libraries",
            "Retag prior Qdrant image",
            "Recreate prior Qdrant image",
            "Restart active consumers after failed transaction",
        ):
            self.assertIn(marker, PLAYBOOK)

    def test_current_qdrant_is_not_recreated_for_ollama_only_update(self) -> None:
        condition = (
            "hermes_memory_servers_qdrant_current\n"
            "            != hermes_memory_servers_qdrant_latest"
        )
        for marker in (
            "Inspect running Qdrant container before image replacement",
            "Pull newest stable Qdrant image",
            "Recreate Qdrant on the stable channel image",
            "Require newest stable Qdrant server",
        ):
            start = PLAYBOOK.index(marker)
            self.assertIn(condition, PLAYBOOK[start:start + 1200])

    def test_gateway_loop_failures_bind_to_registered_results(self) -> None:
        self.assertIn(
            "hermes_memory_servers_gateway_states_before_raw.rc not in [0, 3]",
            PLAYBOOK,
        )
        self.assertIn(
            "hermes_memory_servers_gateway_states_after_config_raw.rc\n"
            "            not in [0, 3]",
            PLAYBOOK,
        )
        self.assertNotIn("failed_when: item.rc not in [0, 3]", PLAYBOOK)

    def test_ollama_unit_tracks_managed_local_runtime(self) -> None:
        self.assertIn("User=ollama", UNIT)
        self.assertIn("WantedBy=multi-user.target", UNIT)
        self.assertIn("{{ hermes_memory_servers_ollama_binary }} serve", UNIT)


if __name__ == "__main__":
    unittest.main()
