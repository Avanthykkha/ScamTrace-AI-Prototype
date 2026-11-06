import json
import os
import sqlite3
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from fastapi.testclient import TestClient

os.environ.setdefault("SCAMTRACE_ENV", "test")
os.environ["SCAMTRACE_API_KEYS"] = json.dumps(
    [
        {"token": "test-admin", "role": "system_admin", "subject": "admin"},
        {"token": "test-investigator", "role": "investigator", "subject": "analyst"},
        {"token": "test-northstar", "role": "integration_client", "subject": "northstar-client", "institution_id": "northstar"},
        {"token": "test-harbor", "role": "institution_admin", "subject": "harbor-admin", "institution_id": "harbor"},
    ]
)

from scamtrace.api import app  # noqa: E402


class ApiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        os.environ["SCAMTRACE_DATABASE"] = os.path.join(self.temp.name, "test.sqlite3")
        self.client_context = TestClient(app)
        self.client = self.client_context.__enter__()
        self.admin = {"X-API-Key": "test-admin"}
        self.investigator = {"X-API-Key": "test-investigator"}

    def tearDown(self):
        self.client_context.__exit__(None, None, None)
        self.temp.cleanup()
        os.environ.pop("SCAMTRACE_DATABASE", None)

    def test_health_and_seeded_demo_signals(self):
        self.assertEqual(self.client.get("/api/v1/health").json()["status"], "ok")
        response = self.client.get("/api/v1/signals", headers=self.investigator)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()["items"]), 14)
        self.assertTrue(all(item["synthetic"] for item in response.json()["items"]))

    def test_auth_validation_and_tenant_scope(self):
        self.assertEqual(self.client.get("/api/v1/signals").status_code, 401)
        response = self.client.post(
            "/api/v1/signals",
            headers={"X-API-Key": "test-northstar"},
            json={
                "external_signal_id": "scope-1",
                "from_institution_id": "harbor",
                "from_account_ref": "x",
                "to_institution_id": "cedar",
                "to_account_ref": "y",
                "amount": "10.00",
                "currency": "INR",
                "channel": "test",
                "occurred_at": datetime.now(timezone.utc).isoformat(),
            },
        )
        self.assertEqual(response.status_code, 404)
        bad = self.client.post(
            "/api/v1/signals",
            headers=self.admin,
            json={"external_signal_id": "invalid", "amount": -1},
        )
        self.assertEqual(bad.status_code, 422)
        self.assertNotIn('"input":-1', bad.text)

    def test_signal_ingestion_is_idempotent_and_audited(self):
        body = {
            "external_signal_id": "api-test-1",
            "institution_id": "northstar",
            "from_institution_id": "northstar",
            "from_account_ref": "unit-a",
            "to_institution_id": "harbor",
            "to_account_ref": "unit-b",
            "amount": "125.00",
            "currency": "INR",
            "channel": "test_transfer",
            "occurred_at": datetime.now(timezone.utc).isoformat(),
            "provenance": {"adapter": "unit-test"},
        }
        first = self.client.post("/api/v1/signals", headers=self.admin, json=body)
        self.assertEqual(first.status_code, 201, first.text)
        self.assertFalse(first.json()["synthetic"])
        duplicate = self.client.post("/api/v1/signals", headers=self.admin, json=body)
        self.assertEqual(duplicate.status_code, 409)
        logs = self.client.get("/api/v1/audit", headers=self.admin).json()
        self.assertTrue(any(event["action"] == "signal.ingest" for event in logs))

    def test_alert_actions_and_case_lifecycle_persist(self):
        alert = self.client.get("/api/v1/alerts", headers=self.investigator).json()["items"][0]
        action = self.client.post(
            f"/api/v1/alerts/{alert['id']}/actions",
            headers=self.investigator,
            json={"action": "acknowledge"},
        )
        self.assertEqual(action.status_code, 200, action.text)
        case = self.client.post(
            "/api/v1/cases",
            headers=self.investigator,
            json={"title": "Investigate transaction trail", "alert_id": alert["id"], "priority": "high"},
        )
        self.assertEqual(case.status_code, 201, case.text)
        case_id = case.json()["id"]
        note = self.client.post(
            f"/api/v1/cases/{case_id}/events",
            headers=self.investigator,
            json={"event_type": "decision", "body": "Continue human review."},
        )
        self.assertEqual(note.status_code, 201)
        updated = self.client.patch(
            f"/api/v1/cases/{case_id}",
            headers=self.investigator,
            json={"status": "under_review"},
        )
        self.assertEqual(updated.status_code, 200, updated.text)
        stored = self.client.get(f"/api/v1/cases/{case_id}", headers=self.investigator).json()
        self.assertEqual(stored["status"], "under_review")
        self.assertEqual(len(stored["events"]), 3)

    def test_geo_endpoint_is_explicitly_synthetic(self):
        result = self.client.get("/api/v1/geo/demo", headers=self.investigator).json()
        self.assertIn("Synthetic", result["label"])
        self.assertTrue(all(item["synthetic"] for item in result["observations"]))
        self.assertGreater(result["indicators"][0]["distance_km"], 1000)

    def test_model_details_do_not_expose_local_artifact_paths(self):
        root = Path(self.temp.name)
        metadata_path = root / "evaluation.json"
        metadata_path.write_text(
            json.dumps(
                {
                    "model_id": "ulb-test",
                    "model_name": "random_forest",
                    "dataset_name": "ULB benchmark",
                    "dataset_path": str(root / "private.csv"),
                    "artifact_path": str(root / "private.joblib"),
                    "artifact_sha256": "private-checksum",
                    "metrics": {},
                }
            ),
            encoding="utf-8",
        )
        db = sqlite3.connect(os.environ["SCAMTRACE_DATABASE"])
        try:
            db.execute(
                """INSERT INTO model_runs
                   (id, model_name, dataset_name, artifact_path, metadata_path, created_at, selected)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    "test-model-run",
                    "random_forest",
                    "ULB benchmark",
                    str(root / "private.joblib"),
                    str(metadata_path),
                    datetime.now(timezone.utc).isoformat(),
                    0,
                ),
            )
            db.commit()
        finally:
            db.close()

        response = self.client.get("/api/v1/models/test-model-run", headers=self.admin)

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["evaluation"]["model_name"], "random_forest")
        for sensitive_value in (str(root), "private-checksum"):
            self.assertNotIn(sensitive_value, response.text)


if __name__ == "__main__":
    unittest.main()
