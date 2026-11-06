from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import sqlite3
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from decimal import Decimal
from typing import Annotated, Any, Literal

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from scamtrace.database import connection, initialize_database
from scamtrace.geo import geo_indicators, synthetic_geo_fixture
from scamtrace.network import analyze_signals, trace_network


logging.basicConfig(level=os.environ.get("SCAMTRACE_LOG_LEVEL", "INFO"))
logger = logging.getLogger("scamtrace.api")

DEMO_KEY = "scamtrace-local-demo-key"
ROLES = {
    "system_admin",
    "institution_admin",
    "investigator",
    "supervisor",
    "integration_client",
    "auditor",
}


class Actor(BaseModel):
    subject: str
    role: str
    institution_id: str | None = None


class SignalCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    external_signal_id: str = Field(min_length=1, max_length=128)
    institution_id: str | None = Field(default=None, min_length=1, max_length=64)
    from_institution_id: str = Field(min_length=1, max_length=64)
    from_account_ref: str = Field(min_length=1, max_length=128)
    to_institution_id: str = Field(min_length=1, max_length=64)
    to_account_ref: str = Field(min_length=1, max_length=128)
    amount: Decimal = Field(gt=0, max_digits=18, decimal_places=2)
    currency: str = Field(min_length=3, max_length=3)
    channel: str = Field(min_length=1, max_length=64)
    occurred_at: datetime
    provenance: dict[str, str] = Field(default_factory=dict)

    @field_validator("currency")
    @classmethod
    def uppercase_currency(cls, value: str) -> str:
        value = value.upper()
        if not value.isalpha():
            raise ValueError("Currency must be a three-letter code.")
        return value

    @field_validator("occurred_at")
    @classmethod
    def timezone_required(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("occurred_at must include a timezone.")
        return value.astimezone(timezone.utc)


class CaseCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    title: str = Field(min_length=3, max_length=200)
    summary: str = Field(default="", max_length=5000)
    priority: Literal["critical", "high", "medium", "low"] = "medium"
    assignee: str | None = Field(default=None, max_length=128)
    alert_id: str | None = None
    institution_id: str | None = None


class CaseUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["new", "under_review", "escalated", "resolved", "closed"] | None = None
    priority: Literal["critical", "high", "medium", "low"] | None = None
    assignee: str | None = Field(default=None, max_length=128)
    summary: str | None = Field(default=None, max_length=5000)

    @model_validator(mode="after")
    def require_update(self) -> "CaseUpdate":
        if not self.model_fields_set:
            raise ValueError("At least one field must be provided.")
        return self


class CaseEventCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    event_type: Literal["note", "decision", "evidence"]
    body: str = Field(min_length=1, max_length=10000)


class AlertAction(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    action: Literal["acknowledge", "escalate", "dismiss"]
    reason: str | None = Field(default=None, max_length=2000)

    @model_validator(mode="after")
    def dismissal_requires_reason(self) -> "AlertAction":
        if self.action == "dismiss" and not self.reason:
            raise ValueError("A dismissal reason is required.")
        return self


class PredictionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    features: dict[str, float] = Field(min_length=1, max_length=64)


@asynccontextmanager
async def lifespan(_: FastAPI):
    initialize_database()
    yield


app = FastAPI(
    title="ScamTrace AI API",
    description=(
        "Local prototype API for authorized, minimized financial signals. "
        "Demo institution and geographic records are synthetic; alerts are leads for human review."
    ),
    version="1.0.0",
    lifespan=lifespan,
)


@app.middleware("http")
async def request_context(request: Request, call_next):
    request.state.request_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))
    response = await call_next(request)
    response.headers["X-Request-ID"] = request.state.request_id
    return response


@app.exception_handler(RequestValidationError)
async def validation_error_handler(request: Request, exc: RequestValidationError):
    return JSONResponse(
        status_code=422,
        content={
            "code": "validation_error",
            "message": "The request did not match the API schema.",
            "request_id": getattr(request.state, "request_id", ""),
            "details": [
                {"location": error["loc"], "type": error["type"], "message": error["msg"]}
                for error in exc.errors()
            ],
        },
    )


@app.exception_handler(HTTPException)
async def http_error_handler(request: Request, exc: HTTPException):
    detail = exc.detail if isinstance(exc.detail, str) else "Request failed."
    return JSONResponse(
        status_code=exc.status_code,
        headers=exc.headers,
        content={
            "code": "request_failed",
            "message": detail,
            "request_id": getattr(request.state, "request_id", ""),
        },
    )


@app.exception_handler(Exception)
async def unexpected_error_handler(request: Request, exc: Exception):
    logger.exception("Unhandled request error (request_id=%s)", getattr(request.state, "request_id", ""))
    return JSONResponse(
        status_code=500,
        content={
            "code": "internal_error",
            "message": "The request could not be completed.",
            "request_id": getattr(request.state, "request_id", ""),
        },
    )


def _configured_keys() -> list[dict[str, Any]]:
    raw = os.environ.get("SCAMTRACE_API_KEYS")
    if raw:
        entries = json.loads(raw)
        if not isinstance(entries, list):
            raise RuntimeError("SCAMTRACE_API_KEYS must be a JSON list.")
        return entries
    if os.environ.get("SCAMTRACE_ENV", "development").lower() != "production":
        return [
            {
                "token": os.environ.get("SCAMTRACE_DEMO_TOKEN", DEMO_KEY),
                "role": "system_admin",
                "subject": "local-demo-admin",
                "institution_id": None,
            }
        ]
    return []


async def authenticate(
    x_api_key: Annotated[str | None, Header(alias="X-API-Key")] = None,
    authorization: Annotated[str | None, Header()] = None,
) -> Actor:
    token = x_api_key
    if token is None and authorization and authorization.lower().startswith("bearer "):
        token = authorization[7:].strip()
    if not token:
        raise HTTPException(status_code=401, detail="A valid API key is required.")
    token_hash = hashlib.sha256(token.encode("utf-8")).digest()
    for item in _configured_keys():
        role = item.get("role")
        expected_hash = item.get("token_hash")
        if expected_hash is not None:
            if not isinstance(expected_hash, str):
                raise RuntimeError("API key token_hash values must be hexadecimal strings.")
            try:
                configured_hash = bytes.fromhex(expected_hash)
            except ValueError as exc:
                raise RuntimeError("API key token_hash values must be hexadecimal strings.") from exc
            if len(configured_hash) != hashlib.sha256().digest_size:
                raise RuntimeError("API key token_hash values must be SHA-256 digests.")
        elif os.environ.get("SCAMTRACE_ENV", "development").lower() != "production":
            expected = item.get("token")
            if not isinstance(expected, str):
                raise RuntimeError("Development API keys need a token and a supported role.")
            configured_hash = hashlib.sha256(expected.encode("utf-8")).digest()
        else:
            raise RuntimeError("Production API key configuration must use token_hash values.")
        if role not in ROLES:
            raise RuntimeError("Each API key configuration needs a supported role.")
        if hmac.compare_digest(token_hash, configured_hash):
            return Actor(
                subject=str(item.get("subject") or "api-client"),
                role=role,
                institution_id=item.get("institution_id"),
            )
    raise HTTPException(status_code=401, detail="A valid API key is required.")


CurrentActor = Annotated[Actor, Depends(authenticate)]


def require_role(actor: Actor, *roles: str) -> None:
    if actor.role not in roles:
        raise HTTPException(status_code=403, detail="Your role is not permitted to perform this action.")


def check_institution_scope(actor: Actor, institution_id: str | None) -> None:
    if actor.role in {"institution_admin", "integration_client"} and actor.institution_id != institution_id:
        raise HTTPException(status_code=404, detail="Resource not found.")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _audit(request: Request, actor: Actor, action: str, resource_type: str, resource_id: str | None) -> None:
    with connection() as db:
        db.execute(
            """INSERT INTO audit_events
               (id, actor, role, institution_id, action, resource_type, resource_id, outcome, request_id, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, 'success', ?, ?)""",
            (
                str(uuid.uuid4()),
                actor.subject,
                actor.role,
                actor.institution_id,
                action,
                resource_type,
                resource_id,
                getattr(request.state, "request_id", ""),
                _now(),
            ),
        )


def _parse_signal(row: sqlite3.Row) -> dict[str, Any]:
    result = dict(row)
    result["provenance"] = json.loads(result["provenance"])
    result["synthetic"] = bool(result["synthetic"])
    return result


def _signals_for(actor: Actor, institution_id: str | None = None) -> list[dict[str, Any]]:
    with connection() as db:
        if actor.role in {"institution_admin", "integration_client"}:
            if actor.institution_id is None:
                raise HTTPException(status_code=403, detail="Institution scope is not configured.")
            if institution_id is not None and institution_id != actor.institution_id:
                raise HTTPException(status_code=404, detail="Resource not found.")
            rows = db.execute(
                "SELECT * FROM transaction_signals WHERE institution_id = ? ORDER BY occurred_at",
                (actor.institution_id,),
            ).fetchall()
        elif institution_id:
            rows = db.execute(
                "SELECT * FROM transaction_signals WHERE institution_id = ? ORDER BY occurred_at",
                (institution_id,),
            ).fetchall()
        else:
            rows = db.execute("SELECT * FROM transaction_signals ORDER BY occurred_at").fetchall()
    return [_parse_signal(row) for row in rows]


def _all_signals_for_analysis() -> list[dict[str, Any]]:
    with connection() as db:
        rows = db.execute("SELECT * FROM transaction_signals ORDER BY occurred_at").fetchall()
    return [_parse_signal(row) for row in rows]


def _alert_dict(row: sqlite3.Row) -> dict[str, Any]:
    item = dict(row)
    item["explanation"] = json.loads(item.pop("explanation"))
    return item


def _case_dict(row: sqlite3.Row, db: sqlite3.Connection) -> dict[str, Any]:
    item = dict(row)
    item["alerts"] = [
        row["alert_id"]
        for row in db.execute(
            "SELECT alert_id FROM investigation_alerts WHERE investigation_id = ? ORDER BY alert_id",
            (item["id"],),
        ).fetchall()
    ]
    item["events"] = [
        dict(event)
        for event in db.execute(
            "SELECT id, actor, event_type, body, created_at FROM investigation_events "
            "WHERE investigation_id = ? ORDER BY created_at",
            (item["id"],),
        ).fetchall()
    ]
    return item


@app.get("/api/v1/health")
def health():
    with connection() as db:
        db.execute("SELECT 1").fetchone()
    return {"status": "ok", "environment": os.environ.get("SCAMTRACE_ENV", "development")}


@app.get("/api/v1/institutions")
def institutions(actor: CurrentActor):
    require_role(actor, "system_admin", "supervisor", "investigator", "institution_admin", "integration_client", "auditor")
    with connection() as db:
        rows = db.execute("SELECT id, name, synthetic, status FROM institutions ORDER BY name").fetchall()
    output = [dict(row) for row in rows]
    if actor.role in {"institution_admin", "integration_client"}:
        output = [row for row in output if row["id"] == actor.institution_id]
    return output


@app.post("/api/v1/signals", status_code=201)
def ingest_signal(payload: SignalCreate, request: Request, actor: CurrentActor):
    require_role(actor, "system_admin", "institution_admin", "integration_client")
    owner = payload.institution_id or actor.institution_id
    if actor.role in {"institution_admin", "integration_client"}:
        if owner != actor.institution_id or payload.from_institution_id != actor.institution_id:
            raise HTTPException(status_code=404, detail="Resource not found.")
    if owner is None:
        raise HTTPException(status_code=422, detail="institution_id is required for this client.")
    signal_id = str(uuid.uuid4())
    occurred_at = payload.occurred_at.isoformat()
    received_at = _now()
    provenance = {**payload.provenance, "api_version": "v1"}
    try:
        with connection() as db:
            known = {
                row["id"]
                for row in db.execute("SELECT id FROM institutions").fetchall()
            }
            if owner not in known or payload.from_institution_id not in known or payload.to_institution_id not in known:
                raise HTTPException(status_code=422, detail="Unknown institution identifier.")
            db.execute(
                """INSERT INTO transaction_signals
                   (id, external_signal_id, institution_id, from_institution_id, from_account_ref,
                    to_institution_id, to_account_ref, amount, currency, channel, occurred_at,
                    received_at, provenance, synthetic)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)""",
                (
                    signal_id,
                    payload.external_signal_id,
                    owner,
                    payload.from_institution_id,
                    payload.from_account_ref,
                    payload.to_institution_id,
                    payload.to_account_ref,
                    str(payload.amount),
                    payload.currency,
                    payload.channel,
                    occurred_at,
                    received_at,
                    json.dumps(provenance),
                ),
            )
    except sqlite3.IntegrityError as exc:
        if "UNIQUE constraint failed" in str(exc):
            raise HTTPException(status_code=409, detail="This external_signal_id was already ingested for the institution.") from exc
        if "FOREIGN KEY constraint failed" in str(exc):
            raise HTTPException(status_code=422, detail="Unknown institution identifier.") from exc
        raise

    signals = _all_signals_for_analysis()
    analysis = analyze_signals(signals)
    source_node = f"{payload.from_institution_id}:{payload.from_account_ref}"
    target_node = f"{payload.to_institution_id}:{payload.to_account_ref}"
    inserted_alerts = []
    with connection() as db:
        for node in {source_node, target_node}:
            metric = analysis["metrics"].get(node)
            if not metric or metric["risk_indicator"] < 45:
                continue
            alert_id = str(uuid.uuid4())
            db.execute(
                """INSERT INTO alerts
                   (id, signal_id, institution_id, account_node, engine, score, status, explanation, created_at, updated_at)
                   VALUES (?, ?, ?, ?, 'network_rule', ?, 'new', ?, ?, ?)""",
                (
                    alert_id,
                    signal_id,
                    owner,
                    node,
                    metric["risk_indicator"],
                    json.dumps(
                        {
                            "reasons": metric["reasons"],
                            "matched_signal_ids": metric["signal_ids"],
                            "limitations": "Rule-based prioritization indicator; not a verified fraud finding.",
                            "synthetic": False,
                        }
                    ),
                    received_at,
                    received_at,
                ),
            )
            inserted_alerts.append(alert_id)
    _audit(request, actor, "signal.ingest", "transaction_signal", signal_id)
    return {
        "id": signal_id,
        "external_signal_id": payload.external_signal_id,
        "institution_id": owner,
        "received_at": received_at,
        "synthetic": False,
        "alerts_created": inserted_alerts,
    }


@app.get("/api/v1/signals")
def list_signals(
    actor: CurrentActor,
    institution_id: str | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
):
    rows = _signals_for(actor, institution_id)
    return {"items": rows[offset : offset + limit], "limit": limit, "offset": offset}


@app.get("/api/v1/alerts")
def list_alerts(
    actor: CurrentActor,
    status: str | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
):
    require_role(actor, "system_admin", "institution_admin", "investigator", "supervisor", "auditor", "integration_client")
    query = "SELECT * FROM alerts"
    params: list[Any] = []
    where = []
    if actor.role in {"institution_admin", "integration_client"}:
        if actor.institution_id is None:
            raise HTTPException(status_code=403, detail="Institution scope is not configured.")
        where.append("institution_id = ?")
        params.append(actor.institution_id)
    if status:
        where.append("status = ?")
        params.append(status)
    if where:
        query += " WHERE " + " AND ".join(where)
    query += " ORDER BY created_at DESC LIMIT ? OFFSET ?"
    params.extend([limit, offset])
    with connection() as db:
        rows = db.execute(query, params).fetchall()
    return {"items": [_alert_dict(row) for row in rows], "limit": limit, "offset": offset}


@app.get("/api/v1/alerts/{alert_id}")
def get_alert(alert_id: str, actor: CurrentActor):
    require_role(actor, "system_admin", "institution_admin", "investigator", "supervisor", "auditor", "integration_client")
    with connection() as db:
        row = db.execute("SELECT * FROM alerts WHERE id = ?", (alert_id,)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Alert not found.")
    check_institution_scope(actor, row["institution_id"])
    return _alert_dict(row)


@app.post("/api/v1/alerts/{alert_id}/actions")
def action_alert(alert_id: str, payload: AlertAction, request: Request, actor: CurrentActor):
    require_role(actor, "system_admin", "institution_admin", "investigator", "supervisor")
    with connection() as db:
        row = db.execute("SELECT * FROM alerts WHERE id = ?", (alert_id,)).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="Alert not found.")
        check_institution_scope(actor, row["institution_id"])
        status = {"acknowledge": "acknowledged", "escalate": "escalated", "dismiss": "dismissed"}[payload.action]
        explanation = json.loads(row["explanation"])
        explanation["last_action"] = {
            "action": payload.action,
            "reason": payload.reason,
            "actor": actor.subject,
            "at": _now(),
        }
        db.execute(
            "UPDATE alerts SET status = ?, explanation = ?, updated_at = ? WHERE id = ?",
            (status, json.dumps(explanation), _now(), alert_id),
        )
    _audit(request, actor, f"alert.{payload.action}", "alert", alert_id)
    return {"id": alert_id, "status": status}


@app.post("/api/v1/alerts/{alert_id}/cases", status_code=201)
def create_case_from_alert(alert_id: str, request: Request, actor: CurrentActor):
    require_role(actor, "system_admin", "institution_admin", "investigator", "supervisor")
    with connection() as db:
        alert = db.execute("SELECT * FROM alerts WHERE id = ?", (alert_id,)).fetchone()
    if alert is None:
        raise HTTPException(status_code=404, detail="Alert not found.")
    check_institution_scope(actor, alert["institution_id"])
    now = _now()
    case_id = str(uuid.uuid4())
    with connection() as db:
        db.execute(
            """INSERT INTO investigations
               (id, title, summary, status, priority, institution_id, created_by, created_at, updated_at)
               VALUES (?, ?, ?, 'new', 'high', ?, ?, ?, ?)""",
            (case_id, f"Review alert {alert_id[:8]}", "Created from an alert for investigator review.", alert["institution_id"], actor.subject, now, now),
        )
        db.execute("INSERT INTO investigation_alerts (investigation_id, alert_id) VALUES (?, ?)", (case_id, alert_id))
        db.execute(
            "INSERT INTO investigation_events (id, investigation_id, actor, event_type, body, created_at) VALUES (?, ?, ?, 'created', ?, ?)",
            (str(uuid.uuid4()), case_id, actor.subject, f"Case created from alert {alert_id}.", now),
        )
    _audit(request, actor, "case.create_from_alert", "investigation", case_id)
    return {"id": case_id, "status": "new", "alert_id": alert_id}


@app.get("/api/v1/accounts/{account_id}/network")
def account_network(
    account_id: str,
    actor: CurrentActor,
    depth: int = Query(default=2, ge=1, le=5),
    max_nodes: int = Query(default=100, ge=1, le=200),
):
    require_role(actor, "system_admin", "institution_admin", "investigator", "supervisor", "auditor", "integration_client")
    signals = _signals_for(actor)
    return trace_network(signals, account_id, depth, max_nodes)


@app.get("/api/v1/cases")
def list_cases(actor: CurrentActor, status: str | None = None):
    require_role(actor, "system_admin", "institution_admin", "investigator", "supervisor", "auditor")
    query = "SELECT * FROM investigations"
    params: list[Any] = []
    conditions = []
    if actor.role == "institution_admin":
        conditions.append("institution_id = ?")
        params.append(actor.institution_id)
    if status:
        conditions.append("status = ?")
        params.append(status)
    if conditions:
        query += " WHERE " + " AND ".join(conditions)
    query += " ORDER BY updated_at DESC LIMIT 500"
    with connection() as db:
        rows = db.execute(query, params).fetchall()
        return [_case_dict(row, db) for row in rows]


@app.post("/api/v1/cases", status_code=201)
def create_case(payload: CaseCreate, request: Request, actor: CurrentActor):
    require_role(actor, "system_admin", "institution_admin", "investigator", "supervisor")
    institution_id = payload.institution_id or actor.institution_id
    if actor.role == "institution_admin" and institution_id != actor.institution_id:
        raise HTTPException(status_code=404, detail="Resource not found.")
    now = _now()
    case_id = str(uuid.uuid4())
    with connection() as db:
        if institution_id and db.execute("SELECT 1 FROM institutions WHERE id = ?", (institution_id,)).fetchone() is None:
            raise HTTPException(status_code=422, detail="Unknown institution identifier.")
        if payload.alert_id:
            alert = db.execute("SELECT * FROM alerts WHERE id = ?", (payload.alert_id,)).fetchone()
            if alert is None:
                raise HTTPException(status_code=404, detail="Alert not found.")
            check_institution_scope(actor, alert["institution_id"])
            if institution_id and alert["institution_id"] != institution_id:
                raise HTTPException(status_code=422, detail="Alert institution does not match the case institution.")
            institution_id = alert["institution_id"]
        db.execute(
            """INSERT INTO investigations
               (id, title, summary, status, priority, institution_id, assignee, created_by, created_at, updated_at)
               VALUES (?, ?, ?, 'new', ?, ?, ?, ?, ?, ?)""",
            (case_id, payload.title, payload.summary, payload.priority, institution_id, payload.assignee, actor.subject, now, now),
        )
        if payload.alert_id:
            db.execute("INSERT INTO investigation_alerts (investigation_id, alert_id) VALUES (?, ?)", (case_id, payload.alert_id))
        db.execute(
            "INSERT INTO investigation_events (id, investigation_id, actor, event_type, body, created_at) VALUES (?, ?, ?, 'created', ?, ?)",
            (str(uuid.uuid4()), case_id, actor.subject, "Case created.", now),
        )
        row = db.execute("SELECT * FROM investigations WHERE id = ?", (case_id,)).fetchone()
        result = _case_dict(row, db)
    _audit(request, actor, "case.create", "investigation", case_id)
    return result


@app.get("/api/v1/cases/{case_id}")
def get_case(case_id: str, actor: CurrentActor):
    require_role(actor, "system_admin", "institution_admin", "investigator", "supervisor", "auditor")
    with connection() as db:
        row = db.execute("SELECT * FROM investigations WHERE id = ?", (case_id,)).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="Case not found.")
        check_institution_scope(actor, row["institution_id"])
        return _case_dict(row, db)


@app.patch("/api/v1/cases/{case_id}")
def update_case(case_id: str, payload: CaseUpdate, request: Request, actor: CurrentActor):
    require_role(actor, "system_admin", "institution_admin", "investigator", "supervisor")
    fields = payload.model_dump(exclude_unset=True)
    now = _now()
    with connection() as db:
        row = db.execute("SELECT * FROM investigations WHERE id = ?", (case_id,)).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="Case not found.")
        check_institution_scope(actor, row["institution_id"])
        if actor.role not in {"system_admin", "supervisor"} and "assignee" in fields:
            raise HTTPException(status_code=403, detail="Only a supervisor may reassign cases.")
        assignments = ", ".join(f"{key} = ?" for key in fields)
        db.execute(
            f"UPDATE investigations SET {assignments}, updated_at = ? WHERE id = ?",
            [*fields.values(), now, case_id],
        )
        changes = ", ".join(f"{key}: {value}" for key, value in fields.items())
        db.execute(
            "INSERT INTO investigation_events (id, investigation_id, actor, event_type, body, created_at) VALUES (?, ?, ?, 'updated', ?, ?)",
            (str(uuid.uuid4()), case_id, actor.subject, f"Updated {changes}.", now),
        )
        result = _case_dict(db.execute("SELECT * FROM investigations WHERE id = ?", (case_id,)).fetchone(), db)
    _audit(request, actor, "case.update", "investigation", case_id)
    return result


@app.post("/api/v1/cases/{case_id}/events", status_code=201)
def append_case_event(case_id: str, payload: CaseEventCreate, request: Request, actor: CurrentActor):
    require_role(actor, "system_admin", "institution_admin", "investigator", "supervisor")
    event_id = str(uuid.uuid4())
    with connection() as db:
        row = db.execute("SELECT institution_id FROM investigations WHERE id = ?", (case_id,)).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="Case not found.")
        check_institution_scope(actor, row["institution_id"])
        db.execute(
            "INSERT INTO investigation_events (id, investigation_id, actor, event_type, body, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (event_id, case_id, actor.subject, payload.event_type, payload.body, _now()),
        )
        db.execute("UPDATE investigations SET updated_at = ? WHERE id = ?", (_now(), case_id))
    _audit(request, actor, f"case.{payload.event_type}", "investigation", case_id)
    return {"id": event_id, "case_id": case_id, "event_type": payload.event_type}


@app.get("/api/v1/geo/demo")
def geo_demo(actor: CurrentActor):
    require_role(actor, "system_admin", "institution_admin", "investigator", "supervisor", "auditor")
    observations = synthetic_geo_fixture()
    return {
        "label": "Synthetic geographic demonstration only; not customer, bank, or ULB locations.",
        "observations": observations,
        "indicators": geo_indicators(observations),
    }


@app.get("/api/v1/audit")
def audit_log(
    actor: CurrentActor,
    limit: int = Query(default=100, ge=1, le=500),
):
    require_role(actor, "system_admin", "supervisor", "auditor")
    with connection() as db:
        rows = db.execute(
            "SELECT id, actor, role, institution_id, action, resource_type, resource_id, outcome, request_id, created_at "
            "FROM audit_events ORDER BY created_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [dict(row) for row in rows]


@app.get("/api/v1/models")
def model_runs(actor: CurrentActor):
    require_role(actor, "system_admin", "supervisor", "investigator", "auditor")
    with connection() as db:
        rows = db.execute(
            "SELECT id, model_name, dataset_name, created_at, selected "
            "FROM model_runs ORDER BY created_at DESC LIMIT 100"
        ).fetchall()
    return [dict(row) for row in rows]


@app.get("/api/v1/models/{run_id}")
def model_run_details(run_id: str, actor: CurrentActor):
    require_role(actor, "system_admin", "supervisor", "investigator", "auditor")
    with connection() as db:
        row = db.execute(
            "SELECT id, model_name, dataset_name, metadata_path, created_at, selected "
            "FROM model_runs WHERE id = ?",
            (run_id,),
        ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Model run not found.")
    metadata_path = row["metadata_path"]
    if not os.path.isfile(metadata_path):
        raise HTTPException(status_code=404, detail="Model evaluation metadata is unavailable.")
    with open(metadata_path, encoding="utf-8") as stream:
        metadata = json.load(stream)
    public_metadata = {
        "model_id", "model_name", "dataset_name", "dataset_file", "dataset_sha256",
        "dataset_rows", "dataset_features", "feature_importance", "split_method",
        "split_sizes", "split_class_counts", "imbalance_handling", "threshold_selection",
        "selected_threshold", "selected_model", "metrics", "trained_at", "limitations",
    }
    evaluation = {key: value for key, value in metadata.items() if key in public_metadata}
    safe_run = {
        key: row[key]
        for key in ("id", "model_name", "dataset_name", "created_at", "selected")
    }
    return {"run": safe_run, "evaluation": evaluation}


@app.post("/api/v1/predictions")
def predict_transaction(payload: PredictionRequest, request: Request, actor: CurrentActor):
    require_role(actor, "system_admin", "investigator", "supervisor", "integration_client")
    try:
        from scamtrace.ml import predict

        result = predict(payload.features)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    _audit(request, actor, "model.predict", "prediction", result["prediction_id"])
    return result
