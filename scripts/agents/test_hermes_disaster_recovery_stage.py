#!/usr/bin/env python3

import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import importlib.util
import json
from pathlib import Path
import sqlite3
import tempfile
import threading
import unittest
import zipfile


SCRIPT = Path(__file__).with_name("hermes-disaster-recovery-stage.py")
SPEC = importlib.util.spec_from_file_location(
    "hermes_disaster_recovery_stage", SCRIPT
)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


class QdrantHandler(BaseHTTPRequestHandler):
    snapshot = b"qdrant-full-storage-snapshot"
    deleted = False
    cluster_status = "disabled"
    point_counts = {"astra": 12, "rigel": 7}
    version = "1.19.0"

    def log_message(self, *_args):
        return

    def _json(self, payload):
        body = json.dumps(payload).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/":
            self._json(
                {
                    "version": self.version,
                    "commit": "test",
                }
            )
        elif self.path == "/cluster":
            self._json(
                {
                    "status": "ok",
                    "result": {"status": self.cluster_status},
                }
            )
        elif self.path == "/collections":
            self._json(
                {
                    "status": "ok",
                    "result": {
                        "collections": [
                            {"name": "astra"},
                            {"name": "rigel"},
                        ]
                    },
                }
            )
        elif self.path == "/snapshots/test.snapshot":
            self.send_response(200)
            self.send_header("Content-Length", str(len(self.snapshot)))
            self.end_headers()
            self.wfile.write(self.snapshot)
        else:
            self.send_error(404)

    def do_POST(self):
        if self.path == "/snapshots?wait=true":
            self._json(
                {
                    "status": "ok",
                    "result": {
                        "name": "test.snapshot",
                        "size": len(self.snapshot),
                        "checksum": MODULE.hashlib.sha256(
                            self.snapshot
                        ).hexdigest(),
                    },
                }
            )
        elif self.path.startswith("/collections/") and self.path.endswith(
            "/points/count"
        ):
            name = self.path.split("/")[2]
            self._json(
                {
                    "status": "ok",
                    "result": {"count": self.point_counts[name]},
                }
            )
        else:
            self.send_error(404)

    def do_DELETE(self):
        if self.path == "/snapshots/test.snapshot":
            type(self).deleted = True
            self._json({"status": "ok", "result": True})
        else:
            self.send_error(404)


class DisasterRecoveryStageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.hermes = self.root / "var/lib/hermes"
        self.automation = self.root / "var/lib/hermes-automation"
        self.stage = self.root / "stage"
        self.status = self.root / "status.json"
        self.automation.mkdir(parents=True)
        for name in ("astra", "rigel"):
            profile = self.hermes / name / ".hermes/profiles" / name
            (profile / "backups").mkdir(parents=True)
            with zipfile.ZipFile(
                profile / "backups/nightly.zip", "w"
            ) as archive:
                archive.writestr("config.yaml", f"profile: {name}\n")
            database = sqlite3.connect(profile / "state.db")
            database.execute("CREATE TABLE state (value TEXT)")
            database.execute(
                "INSERT INTO state VALUES ('private-test-value')"
            )
            database.commit()
            database.close()
        database = sqlite3.connect(self.automation / "health.db")
        database.execute("CREATE TABLE health (value INTEGER)")
        database.commit()
        database.close()
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), QdrantHandler)
        self.thread = threading.Thread(
            target=self.server.serve_forever, daemon=True
        )
        self.thread.start()
        QdrantHandler.deleted = False
        QdrantHandler.cluster_status = "disabled"
        QdrantHandler.point_counts = {"astra": 12, "rigel": 7}
        QdrantHandler.version = "1.19.0"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.temp.cleanup()

    def args(self):
        return argparse.Namespace(
            hermes_root=self.hermes,
            automation_root=self.automation,
            stage_root=self.stage,
            qdrant_url=f"http://127.0.0.1:{self.server.server_port}",
            status_file=self.status,
            no_refresh_native=True,
        )

    def test_stages_dynamic_profiles_sqlite_and_full_qdrant_snapshot(self):
        result = MODULE.stage_backup(self.args())
        self.assertEqual(result["profiles"], 2)
        self.assertEqual(result["sqlite"], 3)
        self.assertEqual(result["qdrantCollections"], 2)
        self.assertTrue(QdrantHandler.deleted)
        manifest = json.loads(
            (self.stage / "current/manifest.json").read_text()
        )
        self.assertEqual(
            [row["profile"] for row in manifest["nativeProfileBackups"]],
            ["astra", "rigel"],
        )
        self.assertEqual(manifest["qdrant"]["clusterStatus"], "disabled")
        self.assertEqual(
            manifest["qdrant"]["pointCounts"], {"astra": 12, "rigel": 7}
        )
        self.assertEqual(
            MODULE.verify_stage(self.stage / "current")["status"], "ok"
        )
        restored = MODULE.verify_qdrant_restore(
            self.stage / "current", self.args().qdrant_url
        )
        self.assertEqual(restored["qdrantRestore"], "ok")
        self.assertEqual(restored["qdrantPoints"], 19)

    def test_rejects_distributed_qdrant_for_full_storage_snapshot(self):
        QdrantHandler.cluster_status = "enabled"
        with self.assertRaisesRegex(MODULE.BackupError, "single-node"):
            MODULE.stage_backup(self.args())

    def test_rejects_symlinked_hermes_root(self):
        real = self.root / "real"
        real.mkdir()
        linked = self.root / "linked"
        linked.symlink_to(real, target_is_directory=True)
        args = self.args()
        args.hermes_root = linked
        with self.assertRaisesRegex(MODULE.BackupError, "invalid-hermes-root"):
            MODULE.stage_backup(args)

    def test_verifier_detects_artifact_tampering(self):
        MODULE.stage_backup(self.args())
        artifact = self.stage / "current/native-profile-backups/astra.zip"
        artifact.write_bytes(b"tampered")
        with self.assertRaisesRegex(MODULE.BackupError, "artifact-hash"):
            MODULE.verify_stage(self.stage / "current")

    def test_prunes_rootless_container_storage_before_sqlite_scan(self):
        account = self.hermes / "astra"
        excluded = account / ".local/share/containers/storage/cache.db"
        excluded.parent.mkdir(parents=True)
        excluded.write_bytes(b"not-a-database")
        databases = MODULE.discover_sqlite_databases([account])
        self.assertNotIn(excluded, [source for source, _relative in databases])

    def test_qdrant_restore_rejects_point_count_mismatch(self):
        MODULE.stage_backup(self.args())
        QdrantHandler.point_counts["astra"] += 1
        with self.assertRaisesRegex(MODULE.BackupError, "point-count-mismatch"):
            MODULE.verify_qdrant_restore(
                self.stage / "current", self.args().qdrant_url
            )

    def test_qdrant_restore_rejects_incompatible_version(self):
        MODULE.stage_backup(self.args())
        QdrantHandler.version = "2.0.0"
        with self.assertRaisesRegex(MODULE.BackupError, "version-incompatible"):
            MODULE.verify_qdrant_restore(
                self.stage / "current", self.args().qdrant_url
            )


if __name__ == "__main__":
    unittest.main()
