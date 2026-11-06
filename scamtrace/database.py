from __future__ import annotations

import os
import sqlite3
import hashlib
import json
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator


ROOT = Path(__file__).resolve().parents[1]


def database_path() -> Path:
    configured = os.environ.get("SCAMTRACE_DATABASE")
    return Path(configured).expanduser() if configured else ROOT / "data" / "processed" / "scamtrace.sqlite3"


@contextmanager
def connection() -> Iterator[sqlite3.Connection]:
    path = database_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path, timeout=15)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys = ON")
    db.execute("PRAGMA journal_mode = WAL")
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def initialize_database() -> None:
    with connection() as db:
        db.executescript(
            """
            CREATE TABLE IF NOT EXISTS institutions (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                synthetic INTEGER NOT NULL DEFAULT 1 CHECK (synthetic IN (0, 1)),
                status TEXT NOT NULL DEFAULT 'demo'
            );
            CREATE TABLE IF NOT EXISTS transaction_signals (
                id TEXT PRIMARY KEY,
                external_signal_id TEXT NOT NULL,
                institution_id TEXT NOT NULL REFERENCES institutions(id),
                from_institution_id TEXT NOT NULL REFERENCES institutions(id),
                from_account_ref TEXT NOT NULL,
                to_institution_id TEXT NOT NULL REFERENCES institutions(id),
                to_account_ref TEXT NOT NULL,
                amount TEXT NOT NULL,
                currency TEXT NOT NULL,
                channel TEXT NOT NULL,
                occurred_at TEXT NOT NULL,
                received_at TEXT NOT NULL,
                provenance TEXT NOT NULL,
                synthetic INTEGER NOT NULL DEFAULT 0 CHECK (synthetic IN (0, 1)),
                UNIQUE(institution_id, external_signal_id)
            );
            CREATE INDEX IF NOT EXISTS idx_signals_time ON transaction_signals(institution_id, occurred_at);
            CREATE INDEX IF NOT EXISTS idx_signals_source ON transaction_signals(from_institution_id, from_account_ref);
            CREATE INDEX IF NOT EXISTS idx_signals_destination ON transaction_signals(to_institution_id, to_account_ref);
            CREATE TABLE IF NOT EXISTS alerts (
                id TEXT PRIMARY KEY,
                signal_id TEXT NOT NULL REFERENCES transaction_signals(id),
                institution_id TEXT NOT NULL REFERENCES institutions(id),
                account_node TEXT NOT NULL,
                engine TEXT NOT NULL,
                score REAL NOT NULL,
                status TEXT NOT NULL DEFAULT 'new',
                explanation TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_alerts_status ON alerts(status, created_at);
            CREATE INDEX IF NOT EXISTS idx_alerts_institution ON alerts(institution_id, created_at);
            CREATE TABLE IF NOT EXISTS investigations (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                summary TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'new',
                priority TEXT NOT NULL DEFAULT 'medium',
                institution_id TEXT REFERENCES institutions(id),
                assignee TEXT,
                created_by TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_investigations_status ON investigations(status, priority);
            CREATE TABLE IF NOT EXISTS investigation_alerts (
                investigation_id TEXT NOT NULL REFERENCES investigations(id),
                alert_id TEXT NOT NULL REFERENCES alerts(id),
                PRIMARY KEY (investigation_id, alert_id)
            );
            CREATE TABLE IF NOT EXISTS investigation_events (
                id TEXT PRIMARY KEY,
                investigation_id TEXT NOT NULL REFERENCES investigations(id),
                actor TEXT NOT NULL,
                event_type TEXT NOT NULL,
                body TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_investigation_events ON investigation_events(investigation_id, created_at);
            CREATE TABLE IF NOT EXISTS audit_events (
                id TEXT PRIMARY KEY,
                actor TEXT NOT NULL,
                role TEXT NOT NULL,
                institution_id TEXT,
                action TEXT NOT NULL,
                resource_type TEXT NOT NULL,
                resource_id TEXT,
                outcome TEXT NOT NULL,
                request_id TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_audit_created ON audit_events(created_at);
            CREATE TABLE IF NOT EXISTS model_runs (
                id TEXT PRIMARY KEY,
                model_name TEXT NOT NULL,
                dataset_name TEXT NOT NULL,
                artifact_path TEXT NOT NULL,
                metadata_path TEXT NOT NULL,
                created_at TEXT NOT NULL,
                selected INTEGER NOT NULL DEFAULT 0
            );
            """
        )
        db.executemany(
            "INSERT OR IGNORE INTO institutions (id, name, synthetic, status) VALUES (?, ?, 1, 'demo')",
            [
                ("northstar", "Northstar Bank"),
                ("harbor", "Harbor Bank"),
                ("cedar", "Cedar Bank"),
            ],
        )
        demo_rows = [
            ("ST-001", "09:00:00", "northstar", "NS-1042", "harbor", "HB-2201", "850", "Card transfer"),
            ("ST-002", "09:06:00", "harbor", "HB-2201", "harbor", "HB-2208", "420", "Instant transfer"),
            ("ST-003", "09:14:00", "cedar", "CD-3010", "northstar", "NS-1184", "1200", "Account transfer"),
            ("ST-004", "09:23:00", "northstar", "NS-1199", "cedar", "CD-3022", "260", "Card transfer"),
            ("ST-005", "10:00:00", "northstar", "NS-VICTIM", "northstar", "NS-4401", "48000", "Instant transfer"),
            ("ST-006", "10:01:10", "northstar", "NS-4401", "harbor", "HB-7720", "45500", "Instant transfer"),
            ("ST-007", "10:02:05", "harbor", "HB-7720", "cedar", "CD-8831", "43800", "Instant transfer"),
            ("ST-008", "10:03:00", "cedar", "CD-8831", "cedar", "CD-9912", "42000", "Cash-out transfer"),
            ("ST-009", "10:02:40", "harbor", "HB-7720", "northstar", "NS-4418", "3200", "Instant transfer"),
            ("ST-010", "10:07:20", "northstar", "NS-4418", "cedar", "CD-9920", "3000", "Instant transfer"),
            ("ST-011", "10:21:00", "cedar", "CD-3051", "harbor", "HB-2110", "670", "Card transfer"),
            ("ST-012", "10:33:00", "northstar", "NS-1188", "cedar", "CD-3090", "1450", "Account transfer"),
            ("ST-013", "10:42:00", "harbor", "HB-2911", "northstar", "NS-1882", "940", "Card transfer"),
            ("ST-014", "10:51:00", "cedar", "CD-3702", "northstar", "NS-2018", "1800", "Account transfer"),
        ]
        for external_id, clock, source_bank, source, destination_bank, destination, amount, channel in demo_rows:
            db.execute(
                """INSERT OR IGNORE INTO transaction_signals
                   (id, external_signal_id, institution_id, from_institution_id, from_account_ref,
                    to_institution_id, to_account_ref, amount, currency, channel, occurred_at,
                    received_at, provenance, synthetic)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'INR', ?, ?, ?, ?, 1)""",
                (
                    f"demo-{external_id.lower()}",
                    external_id,
                    source_bank,
                    source_bank,
                    source,
                    destination_bank,
                    destination,
                    amount,
                    channel,
                    f"2026-10-16T{clock}+00:00",
                    "2026-10-16T11:00:00+00:00",
                    '{"source":"Streamlit prototype demo fixture","label":"synthetic"}',
                ),
            )
    from scamtrace.network import analyze_signals

    with connection() as db:
        rows = db.execute("SELECT * FROM transaction_signals WHERE synthetic = 1 ORDER BY occurred_at").fetchall()
    signals = [dict(row) for row in rows]
    analysis = analyze_signals(signals)
    with connection() as db:
        for account, metric in analysis["metrics"].items():
            if metric["risk_indicator"] < 45:
                continue
            linked = db.execute(
                "SELECT id, institution_id, received_at FROM transaction_signals WHERE id IN (%s) ORDER BY occurred_at DESC LIMIT 1"
                % ",".join("?" for _ in metric["signal_ids"]),
                metric["signal_ids"],
            ).fetchone()
            if linked is None:
                continue
            db.execute(
                """INSERT OR IGNORE INTO alerts
                   (id, signal_id, institution_id, account_node, engine, score, status, explanation, created_at, updated_at)
                   VALUES (?, ?, ?, ?, 'network_rule', ?, 'new', ?, ?, ?)""",
                (
                    "demo-alert-" + hashlib.sha256(account.encode("utf-8")).hexdigest()[:20],
                    linked["id"],
                    linked["institution_id"],
                    account,
                    metric["risk_indicator"],
                    json.dumps(
                        {
                            "reasons": metric["reasons"],
                            "matched_signal_ids": metric["signal_ids"],
                            "limitations": "Rule-based prioritization indicator; not a verified fraud finding.",
                            "synthetic": all(bool(signal.get("synthetic")) for signal in signals if signal["id"] in metric["signal_ids"]),
                        }
                    ),
                    linked["received_at"],
                    linked["received_at"],
                ),
            )
