# ScamTrace AI

ScamTrace AI is a datathon prototype for a centralized financial intelligence layer that helps authorized investigators connect permitted transaction signals across participating institutions.

## Product concept

Participating institutions retain their source records. In this prototype, three fictional banks contribute minimized synthetic transfer signals to a shared analysis layer. Graph analysis connects account activity across institutions and surfaces explainable leads for investigator review.

The proposed customer is an authorized regulator or financial investigation agency (a B2G model). The app demonstrates the investigator workflow and cross-institution intelligence value; it does not connect to real institutions or customer records.

## Problem and proposed solution

Fraud and laundering networks can cross accounts, institutions, channels, and
regions, while each institution sees only part of the activity. ScamTrace
proposes an authorized intelligence layer that accepts minimized signals,
connects permitted transaction relationships, and presents explainable leads
for human investigation. This repository demonstrates that workflow with
fictional records; it does not provide production institutional integration.

## Technology stack

- **Frontend:** React 19, TypeScript, Vite, Tailwind CSS, Recharts, Lucide.
- **Backend:** Python, FastAPI, Pydantic, Pandas, NetworkX, scikit-learn.
- **Persistence and model artifacts:** SQLite and Joblib.
- **Fallback demonstration:** Streamlit.

## Demo workflow

- **Command center:** prioritize accounts using a configurable alert threshold and inspect the evidence behind each score.
- **Trace a network:** explore connected accounts and review a timestamped transfer trail across three fictional banks.
- **Transaction triage:** assess a proposed transfer against the demo's current network exposure, amount, and cross-institution signals.
- **Signal ledger:** filter synthetic signals by institution and download the minimized view as CSV.

## Run locally (Windows PowerShell)

Install the Python dependencies in a PowerShell terminal:

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

If PowerShell blocks activation, run:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\.venv\Scripts\Activate.ps1
```

### Run the React dashboard and API

The existing Streamlit demo remains available as a fallback. For the API-backed
dashboard, use two PowerShell terminals from the project root:

```powershell
# Terminal 1 — FastAPI and interactive API docs
.\.venv\Scripts\python.exe -m uvicorn scamtrace.api:app --host 127.0.0.1 --port 8002
```

```powershell
# Terminal 2 — React/Vite dashboard
npm --prefix .\frontend install
npm --prefix .\frontend run dev -- --port 5175
```

Open `http://127.0.0.1:5175/` for the dashboard or
`http://127.0.0.1:8002/docs` for the API documentation. The UI uses a local
development API key (`scamtrace-local-demo-key`) and fictional, preloaded
institution/signal records. This key is intentionally insecure and must never
be used outside local development.

The database is created at `data/processed/scamtrace.sqlite3` by default.
Set `SCAMTRACE_DATABASE` to override that path. Production deployments must set
`SCAMTRACE_ENV=production` and configure `SCAMTRACE_API_KEYS` as a JSON list
of client objects with a SHA-256 hexadecimal `token_hash`, role, subject, and
optional institution scope. Do not configure production tokens in source code.

### Train and evaluate the ULB benchmark

The checked-in training command reads the real locally stored dataset and
fails with a clear message if it is missing:

```powershell
.\.venv\Scripts\python.exe -m scripts.train_ulb
```

The available OpenML CSV in this repository has no `Time` column. The training
pipeline therefore records and uses a reproducible stratified 70/15/15 split
instead of claiming chronological evaluation. Evaluation numbers are written
only after an actual training run to `data/processed/`; the selected model
artifact is stored under `models/`. Neither raw data nor generated model files
are intended for source control. For Python API tests, install
`requirements-dev.txt` and run:

```powershell
python -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

#### Recorded benchmark run

The following values were produced by an actual run on 2026-11-05 using the
locally available 284,807-row ULB/Worldline CSV. The stratified held-out test
set contained 42,722 records (74 fraud labels). Thresholds were selected on
the validation split by F1; Random Forest was selected by validation Average
Precision. These are offline benchmark results, not partner-bank performance.

| Model | Precision | Recall | F1 | Average Precision | ROC-AUC | Test confusion matrix (TN / FP / FN / TP) |
|---|---:|---:|---:|---:|---:|---|
| Logistic Regression | 0.9333 | 0.7568 | 0.8358 | 0.7914 | 0.9696 | 42,644 / 4 / 18 / 56 |
| Random Forest (selected) | 0.9649 | 0.7432 | 0.8397 | 0.8195 | 0.9485 | 42,646 / 2 / 19 / 55 |

The positive-class score is not calibrated as a real-world fraud probability.
The benchmark has no GPS, account graph, or bank identity and does not validate
the model for cross-institution account transfers. The full split metadata,
thresholds, and metrics are in the generated evaluation JSON.

## Prototype scope

The Streamlit signal ledger and preloaded API demonstration records are
fictional. The React API includes authenticated local signal ingestion,
persisted alerts/cases, audit events, bounded graph tracing, and a separately
labelled synthetic geography fixture. No participating institution is
connected. Rule-based indicators are not trained-model outputs or verified
fraud findings. The ULB-trained benchmark model, when trained, is not validated
for partner-bank account transfers. The transaction triage remains a what-if
illustration and does not request verification, freeze accounts, or control
payments.

A real deployment would require legal authority, institutional agreements,
production identity management, security controls, governance, compatible
validated models, and human review. Local demo authentication and data
minimization are not a guarantee of privacy or legal compliance.

## Architecture

```text
React + TypeScript + Vite
        │ same-origin /api/v1 requests (Vite proxy in local development)
        ▼
FastAPI + Pydantic ── authentication, role checks, validation, audit events
        ├── SQLite: institutions, signals, alerts, cases, events, model runs
        ├── NetworkX: directed transaction graph indicators and tracing
        ├── synthetic-only geography fixture
        └── scikit-learn/joblib: separately trained ULB classification model

Streamlit (app.py) remains as a local fallback demo.
```

The backend is organized under `scamtrace/`: `api.py` exposes versioned
endpoints, `database.py` owns SQLite schema and fictional seed records,
`intelligence.py` computes graph/geo indicators, and `ml.py` trains, loads,
and scores the independent ULB model. Dataset access and training are not
mixed with the synthetic transaction graph. SQLite is the only implemented
database backend; PostgreSQL compatibility has not been implemented.

### Main API surfaces

All endpoints except health require an API key. The React app uses the local
development key by default. See `http://127.0.0.1:8002/docs` while the local
API is running for request/response schemas.

| Endpoint | Purpose |
|---|---|
| `GET /api/v1/health` | Service health |
| `GET /api/v1/institutions` | Demo institution registry |
| `POST`, `GET /api/v1/signals` | Validate/ingest and list minimized signals |
| `GET /api/v1/alerts`, `GET /api/v1/alerts/{id}` | List and inspect indicator alerts |
| `POST /api/v1/alerts/{id}/actions` | Acknowledge, escalate, or dismiss an alert |
| `POST /api/v1/alerts/{id}/cases`, `POST /api/v1/cases` | Create investigation cases |
| `GET /api/v1/accounts/{id}/network` | Bounded directed account trace |
| `GET`, `PATCH /api/v1/cases/{id}` | Read and update investigation cases |
| `POST /api/v1/cases/{id}/events` | Append a case timeline event |
| `GET /api/v1/geo/demo` | Separately labelled synthetic geo fixture |
| `GET /api/v1/models`, `GET /api/v1/models/{id}` | Registered model runs/evaluations |
| `POST /api/v1/predictions` | Score a schema-validated ULB feature vector |
| `GET /api/v1/audit` | Role-restricted audit events |

### Data and database

The SQLite schema includes `institutions`, `transaction_signals`, `alerts`,
`investigations`, `investigation_alerts`, `investigation_events`,
`audit_events`, and `model_runs`. Default demo institution/account/signal data
are fictional. The ULB benchmark and AMLSim are separate datasets and are
never joined to those demo account identities. The included geographic
observations are a synthetic fixture only; they are not derived from ULB or
customer GPS. See [DATASETS.md](./DATASETS.md) for source and evaluation
limitations.

### ML methodology and interpretation

The training script reads the local ULB CSV, validates the feature schema and
binary target, and creates a reproducible stratified train/validation/test
split (70/15/15). It trains Logistic Regression and Random Forest with
class-imbalance weighting, selects the model by validation Average Precision,
selects the decision threshold on validation F1, then reports held-out
precision, recall, F1, Average Precision, ROC-AUC, top-1%-precision, and the
confusion matrix. Inference uses the saved model and saved feature ordering;
the API rejects missing/extra features and non-finite values. It returns an
uncalibrated positive-class score and global model feature importance, not a
per-transaction explanation or a verified fraud decision. Model evaluation
is unavailable until an actual training run has registered an artifact.
Recorded metrics above are the results of the stated local run, not a
guarantee of future or partner-institution performance.

## Configuration and security notes

| Variable | Purpose |
|---|---|
| `SCAMTRACE_DATABASE` | Override the SQLite database location |
| `SCAMTRACE_ENV` | Set to `production` to disable the local fallback key |
| `SCAMTRACE_API_KEYS` | JSON array of client records; production uses SHA-256 `token_hash` values, role, subject, and optional institution scope |
| `SCAMTRACE_DEMO_TOKEN` | Optional local-development token override; never use as a production secret |
| `SCAMTRACE_LOG_LEVEL` | Python log level |
| `SCAMTRACE_MODEL_PATH` | Optional explicit trained-model artifact path |
| `SCAMTRACE_MODEL_METADATA` | Required with `SCAMTRACE_MODEL_PATH`; corresponding evaluation metadata |

Do not put API tokens, customer data, raw datasets, or trained artifacts in
source control. The local demo key is public by design. Before any controlled
deployment, add managed secret storage, HTTPS, rate limiting, operational
monitoring, data-retention controls, independent security review, authorization
and privacy governance, and a tested backup/restore process. Audit data must
not be treated as a substitute for a production tamper-resistant audit system.

## Build, test, and deployment status

From the repository root, run the focused checks:

```powershell
.\.venv\Scripts\python.exe -m compileall -q scamtrace scripts tests
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
npm --prefix .\frontend run build
```

The Streamlit fallback can be started with
`.\.venv\Scripts\python.exe -m streamlit run app.py`.

**Deployment readiness: local demonstration only; not production-ready.**
There is no production deployment manifest, managed database, TLS setup,
production identity provider, or validated multi-instance storage. A
development-only static frontend build is created with
`npm --prefix .\frontend run build`; it is not, by itself, a secure deployment.
Do not expose the demo API or its default key to the public internet. Any
future deployment should serve the UI and API behind a secured same-origin
reverse proxy and complete the security, legal, privacy, and model-governance
work described above first.

## Recommended live demo sequence

1. Start the API and React dashboard using the commands above; open the
   Command Center.
2. Show the synthetic institution and transaction overview, then open the
   alert queue and its matched evidence.
3. Use **Review signals** to inspect linked transaction signal details, then
   **Trace network** and select graph nodes to follow connected synthetic
   activity.
4. Open Geographic Intelligence and call out that every coordinate is a
   separately labelled synthetic fixture.
5. Open Model Intelligence to review the actual held-out benchmark results;
   run the explicitly synthetic inference smoke input if the model artifact is
   present.
6. Create a case, update its status, and review its timeline and audit event.

If no model run is registered, the UI intentionally reports that state rather
than displaying invented results; omit the inference step.
