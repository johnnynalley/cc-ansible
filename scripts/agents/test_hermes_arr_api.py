#!/usr/bin/env python3
"""Focused regressions for the Hermes Arr API broker and Astra plugin."""

from __future__ import annotations

import importlib.util
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
BROKER_PATH = ROOT / "scripts/agents/hermes-arr-api-broker.py"
PLUGIN_PATH = ROOT / "files/hermes/plugins/arr-api/__init__.py"
EXTRACTOR_PATH = ROOT / "scripts/agents/hermes-arr-credential-extract.py"
PLAYBOOK = ROOT / "playbooks/agents/hermes-arr-api.yml"
SERVICE = ROOT / "templates/hermes/hermes-arr-api-broker.service.j2"
HARDENING = ROOT / "templates/hermes/hermes-gateway-hardening.conf.j2"
VARS = ROOT / "inventory/group_vars/hermes_hosts/vars.yml"


def load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


BROKER = load("hermes_arr_api_broker", BROKER_PATH)
PLUGIN = load("hermes_arr_api_plugin", PLUGIN_PATH)
EXTRACTOR = load("hermes_arr_credential_extract", EXTRACTOR_PATH)


def credential(service: str = "sonarr") -> dict:
    return {
        "schemaVersion": 1,
        "service": service,
        "baseUrl": "http://100.108.254.100:8989",
        "apiHeader": "X-Api-Key",
        "apiKey": "a" * 32,
        "pathPrefixes": ["/api/v3/"],
        "statusPath": "/api/v3/system/status",
    }


class Context:
    def __init__(self) -> None:
        self.hooks = []
        self.tools = []

    def register_hook(self, name, callback):
        self.hooks.append((name, callback))

    def register_tool(self, **kwargs):
        self.tools.append(kwargs)


class ArrApiTests(unittest.TestCase):
    def test_loads_only_strict_systemd_credentials(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "sonarr"
            path.write_text(json.dumps(credential()), encoding="utf-8")
            self.assertEqual(BROKER.load_credentials(Path(temporary))["sonarr"]["apiKey"], "a" * 32)
            path.write_text(json.dumps({**credential(), "command": "id"}), encoding="utf-8")
            with self.assertRaisesRegex(BROKER.BrokerError, "invalid-credential"):
                BROKER.load_credentials(Path(temporary))

    def test_path_is_confined_to_declared_api_prefix(self) -> None:
        self.assertEqual(BROKER.validate_path("/api/v3/system/status", ["/api/v3/"]), "/api/v3/system/status")
        for value in ("/api/v1/secret", "/api/v3/../config", "http://evil/api/v3/test"):
            with self.subTest(value=value), self.assertRaises(BROKER.BrokerError):
                BROKER.validate_path(value, ["/api/v3/"])

    def test_secret_mutations_are_denied_recursively(self) -> None:
        for value in (
            {"apiKey": "x"},
            {"fields": [{"password": "x"}]},
            {"fields": [{"name": "password", "value": "x"}]},
            {"tokenValue": "x"},
        ):
            with self.subTest(value=value), self.assertRaisesRegex(BROKER.BrokerError, "secret-mutation-denied"):
                BROKER.reject_secret_mutation(value)
        BROKER.reject_secret_mutation({"title": "Example", "monitored": True})

    def test_indexer_secret_injection_is_exact_and_does_not_mutate_source(self) -> None:
        definition = {
            "name": "Example",
            "fields": [
                {"name": "baseUrl", "value": "https://tracker.example"},
                {"name": "apiKey", "value": "[REDACTED]"},
            ],
        }
        applied = BROKER.inject_indexer_secrets(definition, {"apiKey": "tracker-secret"})
        self.assertEqual(definition["fields"][1]["value"], "[REDACTED]")
        self.assertEqual(applied["fields"][1]["value"], "tracker-secret")
        with self.assertRaisesRegex(BROKER.BrokerError, "secret-field-mismatch"):
            BROKER.inject_indexer_secrets(
                {"fields": [{"name": "apiKey", "value": None}]},
                {"password": "secret"},
            )
        with self.assertRaisesRegex(BROKER.BrokerError, "secret-mutation-denied"):
            BROKER.inject_indexer_secrets(
                {"apiKey": "embedded-secret"},
                {"apiKey": "replacement"},
            )

    def test_indexer_apply_is_path_bounded_and_redacts_response(self) -> None:
        credentials = {"prowlarr": credential("prowlarr")}
        credentials["prowlarr"]["pathPrefixes"] = ["/api/v1/"]
        request = {
            "schemaVersion": 1,
            "action": "prowlarr-indexer-apply",
            "method": "POST",
            "path": "/api/v1/indexer/test",
            "definition": {
                "fields": [{"name": "apiKey", "value": None}],
            },
            "secrets": {"apiKey": "tracker-secret"},
        }
        response = {
            "fields": [{"name": "apiKey", "value": "tracker-secret"}],
        }
        with mock.patch.object(BROKER, "request_json", return_value=(200, response)) as call:
            result = BROKER.prowlarr_indexer_apply(credentials, request)
        self.assertIn(b"tracker-secret", call.call_args.args[0].data)
        self.assertNotIn("tracker-secret", json.dumps(result))
        self.assertEqual(result["body"]["fields"][0]["value"], "[REDACTED]")
        for method, path in (
            ("DELETE", "/api/v1/indexer/1"),
            ("POST", "/api/v1/indexer/1"),
            ("PUT", "/api/v1/indexer/test"),
            ("PUT", "/api/v1/indexer/0"),
        ):
            with self.subTest(method=method, path=path), self.assertRaisesRegex(
                BROKER.BrokerError, "invalid-request"
            ):
                BROKER.prowlarr_indexer_apply(
                    credentials,
                    {**request, "method": method, "path": path},
                )

    def test_schema_search_filters_large_catalog_before_return(self) -> None:
        credentials = {"prowlarr": credential("prowlarr")}
        credentials["prowlarr"]["pathPrefixes"] = ["/api/v1/"]
        schemas = [
            {
                "name": "Example Tracker",
                "implementation": "Cardigann",
                "configContract": "CardigannSettings",
                "fields": [{"name": "apiKey", "value": "secret"}],
            },
            {"name": "Unrelated", "implementation": "Other", "fields": []},
        ]
        with mock.patch.object(BROKER, "request_json", return_value=(200, schemas)) as call:
            result = BROKER.prowlarr_schema_search(
                credentials,
                {"schemaVersion": 1, "action": "prowlarr-schema-search", "query": "Example"},
            )
        self.assertEqual(
            call.call_args.kwargs["max_response_bytes"],
            BROKER.MAX_SCHEMA_RESPONSE_BYTES,
        )
        self.assertEqual(result["body"]["totalMatches"], 1)
        self.assertEqual(
            result["body"]["matches"][0]["fields"][0]["value"],
            "[REDACTED]",
        )

    def test_response_redaction_covers_nested_fields_and_url_queries(self) -> None:
        value = BROKER.sanitize(
            {
                "apiKey": "secret",
                "fields": [{"name": "password", "value": "secret"}],
                "url": "https://example.test/path?apikey=secret&safe=yes",
            }
        )
        self.assertEqual(value["apiKey"], "[REDACTED]")
        self.assertEqual(value["fields"][0]["value"], "[REDACTED]")
        self.assertNotIn("secret", value["url"])
        self.assertIn("safe=yes", value["url"])

    def test_query_rejects_credential_shaped_keys(self) -> None:
        with self.assertRaises(BROKER.BrokerError):
            BROKER.validate_query({"apiKey": "secret"})
        self.assertEqual(BROKER.validate_query({"page": 1, "include": ["a", "b"]}), [("page", "1"), ("include", "a"), ("include", "b")])

    def test_plugin_rejects_unredacted_broker_response(self) -> None:
        with self.assertRaisesRegex(PLUGIN.ArrPluginError, "unredacted"):
            PLUGIN._validate_response(
                {
                    "schemaVersion": 1,
                    "status": "ok",
                    "service": "sonarr",
                    "method": "GET",
                    "path": "/api/v3/system/status",
                    "httpStatus": 200,
                    "body": {"apiKey": "leak"},
                }
            )
        with self.assertRaisesRegex(PLUGIN.ArrPluginError, "unredacted"):
            PLUGIN._validate_response(
                {
                    "schemaVersion": 1,
                    "status": "ok",
                    "service": "sonarr",
                    "method": "GET",
                    "path": "/api/v3/downloadclient",
                    "httpStatus": 200,
                    "body": {"fields": [{"name": "password", "value": "leak"}]},
                }
            )

    def test_plugin_registers_generic_tools_and_bounded_write_policy(self) -> None:
        context = Context()
        PLUGIN.register(context)
        self.assertEqual(
            [item["name"] for item in context.tools],
            [
                "arr_services",
                "arr_api_request",
                "prowlarr_indexer_schema",
                "prowlarr_indexer_apply",
            ],
        )
        self.assertEqual({item["toolset"] for item in context.tools}, {"arr_api"})
        hook = context.hooks[0][1]
        self.assertIsNone(hook(tool_name="arr_api_request", args={"method": "GET"}, turn_id="turn-1"))
        approval = hook(
            tool_name="arr_api_request",
            args={"service": "sonarr", "method": "POST", "path": "/api/v3/command"},
            turn_id="turn-1",
        )
        self.assertEqual(approval["action"], "approve")
        self.assertEqual(approval["rule_key"], "arr-api-write:turn-1")
        blocked = hook(tool_name="arr_api_request", args={"method": "DELETE"}, turn_id="")
        self.assertEqual(blocked["action"], "block")
        indexer = hook(
            tool_name="prowlarr_indexer_apply",
            args={"method": "POST", "path": "/api/v1/indexer/test"},
            turn_id="turn-1",
        )
        self.assertIsNone(indexer)
        blocked_indexer = hook(
            tool_name="prowlarr_indexer_apply",
            args={"method": "PUT", "path": "/api/v1/indexer/15"},
            turn_id="",
        )
        self.assertEqual(blocked_indexer["action"], "block")

    def test_plugin_requires_response_identity_to_match_request(self) -> None:
        wrong = {
            "schemaVersion": 1,
            "status": "ok",
            "service": "radarr",
            "method": "GET",
            "path": "/api/v3/system/status",
            "httpStatus": 200,
            "body": {},
        }
        with mock.patch.object(PLUGIN, "_call", return_value=wrong):
            result = json.loads(
                PLUGIN._handle_request(
                    {"service": "sonarr", "method": "GET", "path": "/api/v3/system/status"}
                )
            )
        self.assertEqual(result["code"], "invalid-broker-response")

    def test_bazarr_extractor_finds_nested_api_key_without_printing_other_secrets(self) -> None:
        self.assertEqual(
            EXTRACTOR.find_key({"auth": {"apikey": "b" * 32}, "provider": {"password": "nope"}}),
            "b" * 32,
        )

    def test_sources_never_embed_live_credentials_or_metered_routes(self) -> None:
        for path in (BROKER_PATH, PLUGIN_PATH, EXTRACTOR_PATH, PLAYBOOK, SERVICE):
            text = path.read_text(encoding="utf-8")
            self.assertNotIn("GEMINI_API_KEY", text)
            self.assertNotIn("OPENAI_API_KEY", text)
            self.assertNotRegex(text, r"[A-Fa-f0-9]{32}.*(?:sonarr|radarr)")

    def test_playbook_is_exactly_gated_and_backup_precedes_secret_publication(self) -> None:
        playbook = PLAYBOOK.read_text(encoding="utf-8")
        variables = VARS.read_text(encoding="utf-8")
        self.assertIn("hermes_arr_api_mode: disabled", variables)
        self.assertIn("enable-credential-isolated-arr-api-for-hermes-astra", variables)
        self.assertLess(
            playbook.index("Back up current Arr API and Astra policy paths"),
            playbook.index("Publish root-private Arr API systemd credentials"),
        )
        self.assertIn("no_log: true", playbook)
        self.assertIn("Restore prior Arr API and Astra policy archive", playbook)
        self.assertIn("Remove paths created only by the failed Arr API promotion", playbook)
        self.assertIn(".get(hermes_arr_api_user) is none", playbook)
        self.assertIn(".get(hermes_arr_api_group) is none", playbook)
        self.assertLess(
            playbook.index("Stage non-propagating Astra Arr broker dependency"),
            playbook.index("Restart changed Arr API broker or ensure it is active"),
        )
        self.assertLess(
            playbook.index("Reload systemd for the isolated Arr API broker"),
            playbook.index("Restart changed Arr API broker or ensure it is active"),
        )
        self.assertLess(
            playbook.index("Stage non-propagating Astra Arr broker dependency"),
            playbook.index("Exercise Arr APIs as Astra before the planned Gateway restart"),
        )
        rescue = playbook[playbook.index("      rescue:") :]
        self.assertLess(
            rescue.index("Restore prior Arr API and Astra policy archive"),
            rescue.index("Stop failed Arr API broker after dependency rollback"),
        )
        self.assertIn("Restore Astra when dependency failure stopped it", rescue)
        self.assertIn("Require prior active Astra state restored", rescue)
        self.assertIn("Wait for Astra native readiness after Arr API promotion", playbook)

    def test_broker_service_owns_credentials_and_has_no_general_privilege(self) -> None:
        service = SERVICE.read_text(encoding="utf-8")
        self.assertIn("User={{ hermes_arr_api_user }}", service)
        self.assertIn("LoadCredential={{ service.name }}:", service)
        self.assertIn("IPAddressDeny=any", service)
        self.assertIn("IPAddressAllow={{ address }}", service)
        self.assertIn("NoNewPrivileges=true", service)
        self.assertIn("CapabilityBoundingSet=", service)
        self.assertIn("ExecStart={{ hermes_arr_api_python }}", service)
        self.assertIn("--allowed-uid {{ hermes_arr_api_astra_profile.uid }}", service)
        self.assertNotIn("hermes_production_cutover_user_uid", service)
        self.assertNotIn("/var/run/docker.sock", service)
        self.assertNotIn("sudo", service)

    def test_gateway_receives_only_socket_and_plugin_not_arr_credentials(self) -> None:
        hardening = HARDENING.read_text(encoding="utf-8")
        self.assertIn("Wants=hermes-arr-api-broker.service", hardening)
        self.assertNotIn("Requires=hermes-arr-api-broker.service", hardening)
        self.assertIn("BindReadOnlyPaths={{ hermes_arr_api_runtime_dir }}", hardening)
        self.assertIn("hermes_arr_api_plugin_managed_root", hardening)
        self.assertNotIn("LoadCredential=sonarr", hardening)
        self.assertNotIn("LoadCredential=radarr", hardening)

    def test_validator_requires_the_root_managed_private_plugin_mode(self) -> None:
        validator = (ROOT / "scripts/agents/hermes-arr-api-validate.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("stat.S_IMODE(item.st_mode) == 0o440", validator)
        self.assertNotIn("0o444, 0o555", validator)

    def test_playbook_probes_all_managed_services_read_only_as_real_astra(self) -> None:
        playbook = PLAYBOOK.read_text(encoding="utf-8")
        variables = VARS.read_text(encoding="utf-8")
        for name in ("sonarr", "radarr", "prowlarr", "bazarr"):
            self.assertIn(f"- name: {name}", variables)
        self.assertIn("Verify every Arr credential against its read-only status endpoint", playbook)
        self.assertIn("Exercise every Arr API as the real Astra identity", playbook)
        self.assertIn("--user\n              - hermes-astra", playbook)
        self.assertIn("Deploy additive-safe managed plugin validators", playbook)
        for variable in (
            "hermes_star_privacy_validator_live",
            "hermes_docker_inventory_validator_live",
            "hermes_discord_parity_validator_live",
        ):
            self.assertIn(variable, playbook)

    def test_only_changed_arr_runtime_restarts_astra(self) -> None:
        playbook = PLAYBOOK.read_text(encoding="utf-8")
        restart = playbook[
            playbook.index("Restart Astra once for Arr API promotion") :
            playbook.index("Wait for Astra native readiness after Arr API promotion")
        ]
        self.assertIn("hermes-gateway-astra.service", restart)
        self.assertIn("hermes_arr_api_restart_required", restart)
        self.assertNotIn("hermes_shadow_runtime_binary", restart)
        self.assertNotIn("gateway\n", restart)
        self.assertNotIn("hermes-gateway-dubble", playbook)
        self.assertNotIn("hermes-gateway-rigel", playbook)


if __name__ == "__main__":
    unittest.main()
