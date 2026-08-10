from __future__ import annotations

import base64
import importlib.machinery
import importlib.util
import json
import sys
import unittest
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]


def load_worker() -> Any:
    path = ROOT / "run-cloud-analysis"
    loader = importlib.machinery.SourceFileLoader("media_inbox_cloud_worker", str(path))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    if spec is None:
        raise RuntimeError("could not load cloud worker")
    module = importlib.util.module_from_spec(spec)
    sys.modules[loader.name] = module
    loader.exec_module(module)
    return module


class CloudWorkerTests(unittest.TestCase):
    def test_claim_decodes_only_a_valid_candidate_and_prompt(self) -> None:
        module = load_worker()
        asset_id = "12345678-1234-1234-1234-123456789abc"
        claim = {
            "ok": True,
            "schema": 1,
            "candidate": {
                "candidate_id": asset_id,
                "prompt_base64": base64.b64encode(b"trusted outer prompt").decode(),
            },
        }
        self.assertEqual(
            module.parse_claim(json.dumps(claim)),
            (asset_id, "trusted outer prompt"),
        )
        claim["candidate"]["candidate_id"] = "../../etc/passwd"
        with self.assertRaises(module.WorkerError):
            module.parse_claim(json.dumps(claim))

    def test_model_envelope_requires_exact_openai_sol_route_and_strict_json(
        self,
    ) -> None:
        module = load_worker()
        payload = {"decision": "identified"}
        envelope = {
            "ok": True,
            "transport": "local",
            "provider": "openai",
            "model": "gpt-5.6-sol",
            "outputs": [{"text": json.dumps(payload), "mediaUrl": None}],
        }
        self.assertEqual(
            module.extract_model_payload(
                json.dumps(envelope), expected_model="openai/gpt-5.6-sol"
            ),
            payload,
        )
        envelope["provider"] = "ollama-cloud"
        with self.assertRaisesRegex(module.WorkerError, "unexpected analysis route"):
            module.extract_model_payload(
                json.dumps(envelope), expected_model="openai/gpt-5.6-sol"
            )


if __name__ == "__main__":
    unittest.main()
