#!/usr/bin/env python3

import http.client
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

SCRIPT = Path(__file__).with_name("health-receiver.py")
CHECK_SCRIPT = Path(__file__).with_name("health-receiver-check.py")
REPOSITORY = Path(__file__).resolve().parents[2]
PLAYBOOK = REPOSITORY / "playbooks/agents/hermes-health-receiver.yml"
HOST_VARS = REPOSITORY / "inventory/host_vars/jn-t14s-lin/hermes.yml"
GROUP_VARS = REPOSITORY / "inventory/group_vars/hermes_hosts/vars.yml"
SITE = REPOSITORY / "site.yml"
GATEWAY_HARDENING = (
    REPOSITORY / "templates/hermes/hermes-gateway-hardening.conf.j2"
)
TOKEN = "dummy" * 8


def request(port, method, path, body=None, token=None, api_key=None):
    headers = {}
    if token is not None:
        headers["Authorization"] = f"Bearer {token}"
    if api_key is not None:
        headers["X-API-Key"] = api_key
    if body is not None:
        headers["Content-Type"] = "application/json"
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    connection.request(method, path, body=body, headers=headers)
    response = connection.getresponse()
    payload = response.read()
    connection.close()
    return response.status, payload


class HealthReceiverSecurityTests(unittest.TestCase):
    def test_startup_requires_token(self):
        environment = os.environ.copy()
        environment.pop("HEALTH_RECEIVER_TOKEN", None)
        environment.pop("HEALTH_RECEIVER_TOKEN_FILE", None)
        result = subprocess.run(
            [sys.executable, str(SCRIPT)],
            env=environment,
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        self.assertEqual(result.returncode, 1)
        self.assertIn("token of at least 32 bytes is required", result.stderr)

    def test_request_security_controls(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            environment = {
                "HEALTH_RECEIVER_TOKEN": TOKEN,
                "HEALTH_RECEIVER_TOKEN_FILE": "",
                "HEALTH_RECEIVER_BIND": "127.0.0.1",
                "HEALTH_RECEIVER_ALLOWED_SOURCES": "127.0.0.1",
                "HEALTH_RECEIVER_MAX_BODY_BYTES": "2048",
                "HEALTH_RECEIVER_RATE_LIMIT": "20",
                "HEALTH_RECEIVER_RATE_WINDOW_SECONDS": "60",
                "HEALTH_RECEIVER_MAX_JSON_DEPTH": "16",
                "HEALTH_RECEIVER_MAX_JSON_NODES": "1000",
                "HEALTH_RECEIVER_MAX_COLLECTION_ITEMS": "100",
                "HEALTH_RECEIVER_MAX_STRING_BYTES": "128",
                "HEALTH_DB_PATH": str(Path(temp_dir) / "health.db"),
            }
            with mock.patch.dict(os.environ, environment, clear=False):
                spec = importlib.util.spec_from_file_location(
                    "health_receiver_test", SCRIPT
                )
                health = importlib.util.module_from_spec(spec)
                self.assertIsNotNone(spec.loader)
                spec.loader.exec_module(health)

            health.init_db()
            server = health.HTTPServer(("127.0.0.1", 0), health.HealthReceiver)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            self.addCleanup(server.server_close)
            self.addCleanup(thread.join, 5)
            self.addCleanup(server.shutdown)
            port = server.server_address[1]

            self.assertEqual(request(port, "GET", "/health")[0], 401)
            status, payload = request(port, "GET", "/health", token=TOKEN)
            self.assertEqual(status, 200)
            self.assertEqual(json.loads(payload)["status"], "running")
            self.assertEqual(request(port, "GET", "/health", api_key=TOKEN)[0], 200)
            self.assertEqual(request(port, "GET", "/wrong", token=TOKEN)[0], 404)

            metric_body = json.dumps(
                {
                    "metrics": [
                        {
                            "name": "step_count",
                            "units": "count",
                            "data": [
                                {
                                    "qty": 100,
                                    "date": "2026-08-08 12:00:00 -0500",
                                    "source": "test",
                                }
                            ],
                        }
                    ]
                }
            )
            status, payload = request(
                port,
                "POST",
                "/health",
                body=metric_body,
                token=TOKEN,
            )
            self.assertEqual(status, 200)
            self.assertTrue(json.loads(payload)["ok"])
            self.assertEqual(json.loads(payload)["stored"]["metrics"], 1)
            status, payload = request(
                port, "POST", "/health", body=metric_body, token=TOKEN
            )
            self.assertEqual(status, 200)
            self.assertEqual(json.loads(payload)["stored"]["metrics"], 0)

            token_file = Path(temp_dir) / "token"
            token_file.write_text(TOKEN, encoding="utf-8")
            token_file.chmod(0o640)
            check_result = subprocess.run(
                [
                    sys.executable,
                    str(CHECK_SCRIPT),
                    "--url",
                    f"http://127.0.0.1:{port}/health",
                    "--token-file",
                    str(token_file),
                    "--require-metrics",
                    "--write-probe",
                ],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
            self.assertEqual(check_result.returncode, 0, check_result.stderr)
            self.assertEqual(
                check_result.stdout.strip(),
                "OK: isolated Health receiver passed authenticated validation",
            )

            self.assertEqual(
                request(port, "POST", "/health", body="[]", token=TOKEN)[0],
                200,
            )
            self.assertEqual(
                request(port, "POST", "/health", body="1", token=TOKEN)[0],
                400,
            )
            self.assertEqual(
                request(port, "POST", "/health", body="x" * 2049, token=TOKEN)[0],
                413,
            )
            self.assertEqual(
                request(port, "POST", "/health", body="[1]", token=TOKEN)[0],
                400,
            )

            invalid_number = '{"metrics":[{"name":"steps","data":[{"qty":NaN}]}]}'
            self.assertEqual(
                request(port, "POST", "/health", body=invalid_number, token=TOKEN)[0],
                400,
            )

            health.MAX_STRING_BYTES = 4
            self.assertEqual(
                request(
                    port,
                    "POST",
                    "/health",
                    body='{"x":"12345"}',
                    token=TOKEN,
                )[0],
                400,
            )
            health.MAX_STRING_BYTES = 128

            health.ALLOWED_SOURCES = {"192.0.2.1"}
            self.assertEqual(request(port, "GET", "/health", token=TOKEN)[0], 403)
            health.ALLOWED_SOURCES = {"127.0.0.1"}

            health.REQUEST_TIMES.clear()
            health.RATE_LIMIT = 2
            self.assertEqual(request(port, "GET", "/health", token=TOKEN)[0], 200)
            self.assertEqual(request(port, "GET", "/health", token=TOKEN)[0], 200)
            self.assertEqual(request(port, "GET", "/health", token=TOKEN)[0], 429)


class HermesHealthDeploymentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.playbook = PLAYBOOK.read_text(encoding="utf-8")
        cls.host_vars = HOST_VARS.read_text(encoding="utf-8")
        cls.group_vars = GROUP_VARS.read_text(encoding="utf-8")
        cls.site = SITE.read_text(encoding="utf-8")
        cls.gateway_hardening = GATEWAY_HARDENING.read_text(encoding="utf-8")

    def test_live_runtime_is_hermes_native(self):
        self.assertIn("playbooks/agents/hermes-health-receiver.yml", self.site)
        self.assertIn("hermes-health-receiver.service", self.playbook)
        self.assertIn("hermes-health-summary.timer", self.playbook)
        self.assertIn("/usr/local/libexec/hermes-health", self.playbook)
        self.assertIn("/var/lib/hermes/health", self.host_vars)
        inventory = self.group_vars + self.host_vars
        self.assertIn("/etc/hermes/health", inventory)
        self.assertNotIn("/var/lib/openclaw-health", self.playbook + inventory)
        self.assertNotIn("/etc/openclaw-health", self.playbook + inventory)
        self.assertNotIn("openclaw_health_receiver", self.playbook + inventory)

    def test_cutover_is_rollback_backed_and_write_validated(self):
        self.assertIn("Require expected Tailscale NFS rollback origin", self.playbook)
        self.assertIn("/srv/live-rollbacks/jn-t14s-lin/hermes-health", self.host_vars)
        self.assertIn("Back up final legacy Health database consistently", self.playbook)
        self.assertIn("Back up pre-cutover Hermes Health database consistently", self.playbook)
        self.assertIn("Verify final Hermes Health database integrity", self.playbook)
        self.assertGreaterEqual(self.playbook.count("--write-probe"), 2)

    def test_old_user_service_is_disabled_only_after_validation(self):
        verified = self.playbook.index("Verify authenticated production Health receiver")
        disabled = self.playbook.index("Disable legacy user Health receiver after validation")
        self.assertLess(verified, disabled)

    def test_routine_production_does_not_read_migration_sources(self):
        self.assertIn("hermes_health_receiver_migration_inputs_required", self.playbook)
        for task in (
            "Resolve legacy Health receiver account",
            "Inspect legacy Health token source",
            "Inspect legacy Health database",
            "Verify retained Health source database integrity",
            "Copy Health receiver token without exposing it to Ansible output",
        ):
            block = self.playbook.split(f"- name: {task}", 1)[1].split("\n    - name:", 1)[0]
            self.assertIn(
                "when: hermes_health_receiver_migration_inputs_required | bool",
                block,
            )
        self.assertIn("Require protected Hermes Health token", self.playbook)

    def test_only_astra_receives_aggregate_report_access(self):
        self.assertIn(
            "(' ' ~ hermes_health_report_group) "
            "if hermes_profile.name == 'astra' else ''",
            self.gateway_hardening,
        )
        self.assertIn(
            "BindReadOnlyPaths={{ hermes_health_receiver_report_dir }}",
            self.gateway_hardening,
        )
        self.assertIn(
            "InaccessiblePaths={{ hermes_health_receiver_db }} "
            "{{ hermes_health_receiver_config_dir }}",
            self.gateway_hardening,
        )
        self.assertIn(
            "{% if hermes_profile.name == 'astra' %}\n"
            "BindReadOnlyPaths={{ hermes_star_privacy_plugin_managed_root }}:"
            "{{ hermes_star_privacy_plugin_runtime_root }}\n"
            "BindReadOnlyPaths={{ hermes_health_receiver_report_dir }}\n"
            "InaccessiblePaths={{ hermes_health_receiver_db }} "
            "{{ hermes_health_receiver_config_dir }}",
            self.gateway_hardening,
        )


if __name__ == "__main__":
    unittest.main()
