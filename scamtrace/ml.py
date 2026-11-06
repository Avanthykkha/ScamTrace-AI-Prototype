from __future__ import annotations

import hashlib
import json
import math
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    average_precision_score,
    confusion_matrix,
    f1_score,
    precision_recall_curve,
    precision_score,
    recall_score,
    roc_auc_score,
)
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.model_selection import train_test_split

from scamtrace.database import connection, initialize_database


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATASET = ROOT / "data" / "raw" / "ulb_creditcard.csv"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_dataset(path: Path) -> tuple[pd.DataFrame, pd.Series]:
    if not path.is_file():
        raise FileNotFoundError(
            f"ULB dataset not found at {path}. Run `python scripts/fetch_ulb.py` first."
        )
    frame = pd.read_csv(path)
    if "Class" not in frame.columns:
        raise ValueError("Expected the ULB label column 'Class'.")
    y = pd.to_numeric(frame.pop("Class"), errors="raise").astype("int8")
    if set(y.unique()) != {0, 1}:
        raise ValueError("The ULB Class column must contain both labels 0 and 1.")
    expected_features = {*(f"V{i}" for i in range(1, 29)), "Amount"}
    allowed_features = expected_features | {"Time"}
    actual_features = set(frame.columns)
    if not expected_features.issubset(actual_features) or not actual_features.issubset(allowed_features):
        missing = sorted(expected_features - actual_features)
        unexpected = sorted(actual_features - allowed_features)
        raise ValueError(
            f"Unexpected ULB feature schema; missing={missing}, unexpected={unexpected}."
        )
    if frame.empty or frame.isna().all(axis=None):
        raise ValueError("Dataset features are empty.")
    frame = frame.apply(pd.to_numeric, errors="raise")
    if not np.isfinite(frame.to_numpy(dtype=np.float64)).all():
        raise ValueError("Dataset features contain non-finite values.")
    return frame, y


def _evaluation_splits(frame: pd.DataFrame, y: pd.Series):
    indices = np.arange(len(frame))
    if "Time" in frame.columns:
        order = np.argsort(frame["Time"].to_numpy(), kind="stable")
        train_end = int(len(order) * 0.70)
        validation_end = int(len(order) * 0.85)
        if train_end == 0 or validation_end <= train_end or validation_end >= len(order):
            raise ValueError("Dataset is too small for 70/15/15 chronological splits.")
        train_indices = order[:train_end]
        validation_indices = order[train_end:validation_end]
        test_indices = order[validation_end:]
        split_method = "chronological 70% train / 15% validation / 15% test, sorted by Time"
    else:
        train_indices, remaining_indices = train_test_split(
            indices, train_size=0.70, random_state=42, stratify=y
        )
        validation_indices, test_indices = train_test_split(
            remaining_indices,
            test_size=0.50,
            random_state=42,
            stratify=y.iloc[remaining_indices],
        )
        split_method = (
            "stratified random 70% train / 15% validation / 15% test, "
            "random_state=42; source CSV has no Time column"
        )
    x_train, x_validation, x_test = (
        frame.iloc[train_indices],
        frame.iloc[validation_indices],
        frame.iloc[test_indices],
    )
    y_train, y_validation, y_test = (
        y.iloc[train_indices],
        y.iloc[validation_indices],
        y.iloc[test_indices],
    )
    for label, values in (("train", y_train), ("validation", y_validation), ("test", y_test)):
        if values.nunique() != 2:
            raise ValueError(f"The chronological {label} split does not contain both classes.")
    return x_train, x_validation, x_test, y_train, y_validation, y_test, split_method


def _best_f1_threshold(y_true: pd.Series, scores: np.ndarray) -> float:
    precision, recall, thresholds = precision_recall_curve(y_true, scores)
    if thresholds.size == 0:
        raise ValueError("Validation split cannot support threshold selection.")
    f1 = 2 * precision[:-1] * recall[:-1] / np.maximum(precision[:-1] + recall[:-1], 1e-12)
    return float(thresholds[int(np.nanargmax(f1))])


def _metrics(y_true: pd.Series, scores: np.ndarray, threshold: float) -> dict[str, Any]:
    predictions = (scores >= threshold).astype("int8")
    tn, fp, fn, tp = confusion_matrix(y_true, predictions, labels=[0, 1]).ravel()
    top_k = max(1, int(math.ceil(len(y_true) * 0.01)))
    top_indices = np.argsort(scores)[-top_k:]
    top_k_precision = float(y_true.iloc[top_indices].mean())
    return {
        "samples": int(len(y_true)),
        "fraud_count": int(y_true.sum()),
        "fraud_prevalence": float(y_true.mean()),
        "threshold": float(threshold),
        "precision": float(precision_score(y_true, predictions, zero_division=0)),
        "recall": float(recall_score(y_true, predictions, zero_division=0)),
        "f1": float(f1_score(y_true, predictions, zero_division=0)),
        "average_precision": float(average_precision_score(y_true, scores)),
        "roc_auc": float(roc_auc_score(y_true, scores)),
        "confusion_matrix": {"true_negative": int(tn), "false_positive": int(fp), "false_negative": int(fn), "true_positive": int(tp)},
        "false_positive_rate": float(fp / (fp + tn)) if fp + tn else 0.0,
        "false_negative_rate": float(fn / (fn + tp)) if fn + tp else 0.0,
        "top_1_percent_precision": top_k_precision,
        "top_k": top_k,
    }


def train_models(dataset_path: Path = DEFAULT_DATASET) -> dict[str, Any]:
    dataset_path = Path(dataset_path).resolve()
    frame, y = _load_dataset(dataset_path)
    x_train, x_validation, x_test, y_train, y_validation, y_test, split_method = _evaluation_splits(frame, y)
    print(
        f"Loaded {len(frame):,} ULB rows; {split_method}; split sizes "
        f"train={len(y_train):,}, validation={len(y_validation):,}, test={len(y_test):,}."
    )

    models = {
        "logistic_regression": make_pipeline(
            StandardScaler(),
            LogisticRegression(class_weight="balanced", max_iter=500, solver="liblinear", random_state=42),
        ),
        "random_forest": RandomForestClassifier(
            n_estimators=100,
            max_depth=16,
            min_samples_leaf=2,
            class_weight="balanced_subsample",
            n_jobs=-1,
            random_state=42,
        ),
    }
    results: dict[str, Any] = {}
    for name, estimator in models.items():
        print(f"Training {name}...")
        estimator.fit(x_train, y_train)
        scores = estimator.predict_proba(x_validation)[:, list(estimator.classes_).index(1)]
        threshold = _best_f1_threshold(y_validation, scores)
        results[name] = {
            "validation": _metrics(y_validation, scores, threshold),
            "test": None,
        }
    selected_name = max(
        results,
        key=lambda name: (results[name]["validation"]["average_precision"], results[name]["validation"]["f1"]),
    )
    for name, estimator in models.items():
        test_scores = estimator.predict_proba(x_test)[:, list(estimator.classes_).index(1)]
        threshold = results[name]["validation"]["threshold"]
        results[name]["test"] = _metrics(y_test, test_scores, threshold)

    selected_model = models[selected_name]
    feature_names = list(frame.columns)
    if selected_name == "random_forest":
        importances = selected_model.feature_importances_
    else:
        importances = np.abs(selected_model.named_steps["logisticregression"].coef_[0])
    ranked_features = sorted(
        [
            {"name": name, "importance": float(value)}
            for name, value in zip(feature_names, importances, strict=True)
        ],
        key=lambda item: item["importance"],
        reverse=True,
    )
    now = datetime.now(timezone.utc)
    version = now.strftime("%Y%m%dT%H%M%SZ")
    artifact_path = ROOT / "models" / f"ulb_{selected_name}_{version}.joblib"
    metadata_path = ROOT / "data" / "processed" / f"ulb_{version}.json"
    artifact_path.parent.mkdir(parents=True, exist_ok=True)
    metadata_path.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(selected_model, artifact_path, compress=3)
    metadata = {
        "model_id": f"ulb-{selected_name}-{version}",
        "model_name": selected_name,
        "dataset_name": "ULB/Worldline Credit Card Fraud Detection",
        "dataset_file": dataset_path.name,
        "dataset_sha256": _sha256(dataset_path),
        "dataset_rows": len(frame),
        "dataset_features": feature_names,
        "feature_importance": ranked_features,
        "split_method": split_method,
        "split_sizes": {"train": len(y_train), "validation": len(y_validation), "test": len(y_test)},
        "split_class_counts": {
            "train": y_train.value_counts().sort_index().to_dict(),
            "validation": y_validation.value_counts().sort_index().to_dict(),
            "test": y_test.value_counts().sort_index().to_dict(),
        },
        "imbalance_handling": "class_weight='balanced' for Logistic Regression; balanced_subsample for Random Forest",
        "threshold_selection": "F1 maximization on the validation split",
        "selected_threshold": results[selected_name]["validation"]["threshold"],
        "selected_model": selected_name,
        "metrics": results,
        "trained_at": now.isoformat(),
        "limitations": [
            "This is an offline benchmark, not a validated model for partner bank transfers.",
            "The dataset has no customer GPS, account graph, or institution identifiers.",
            "The positive-class model score is not a calibrated fraud probability.",
        ],
        "artifact_sha256": None,
    }
    metadata_path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    metadata["artifact_sha256"] = _sha256(artifact_path)
    metadata_path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    run_id = str(uuid.uuid4())
    initialize_database()
    with connection() as db:
        db.execute("UPDATE model_runs SET selected = 0")
        db.execute(
            """INSERT INTO model_runs
               (id, model_name, dataset_name, artifact_path, metadata_path, created_at, selected)
               VALUES (?, ?, ?, ?, ?, ?, 1)""",
            (run_id, selected_name, metadata["dataset_name"], str(artifact_path), str(metadata_path), now.isoformat()),
        )
    print(f"Selected {selected_name} by validation average precision.")
    print(f"Test metrics: {json.dumps(results[selected_name]['test'], sort_keys=True)}")
    print(f"Model: {artifact_path}")
    print(f"Evaluation: {metadata_path}")
    return metadata


def load_selected_model() -> tuple[Any, dict[str, Any]]:
    configured = os.environ.get("SCAMTRACE_MODEL_PATH")
    if configured:
        artifact_path = Path(configured).expanduser().resolve()
        configured_metadata = os.environ.get("SCAMTRACE_MODEL_METADATA")
        if not configured_metadata:
            raise RuntimeError("SCAMTRACE_MODEL_METADATA is required with SCAMTRACE_MODEL_PATH.")
        metadata_path = Path(configured_metadata).expanduser().resolve()
    else:
        with connection() as db:
            row = db.execute(
                "SELECT artifact_path, metadata_path FROM model_runs WHERE selected = 1 ORDER BY created_at DESC LIMIT 1"
            ).fetchone()
        if row is None:
            raise FileNotFoundError("No trained model is registered. Run `python scripts/train_ulb.py` first.")
        artifact_path = Path(row["artifact_path"]).resolve()
        metadata_path = Path(row["metadata_path"]).resolve()
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    if not artifact_path.is_file():
        raise FileNotFoundError(f"Trained model artifact not found: {artifact_path}")
    if _sha256(artifact_path) != metadata.get("artifact_sha256"):
        raise ValueError("Model artifact checksum does not match its evaluation metadata.")
    return joblib.load(artifact_path), metadata


def predict(features: dict[str, float]) -> dict[str, Any]:
    model, metadata = load_selected_model()
    expected = metadata["dataset_features"]
    if set(features) != set(expected):
        missing, extra = sorted(set(expected) - set(features)), sorted(set(features) - set(expected))
        raise ValueError(f"Feature schema mismatch; missing={missing}, extra={extra}.")
    if not all(math.isfinite(value) for value in features.values()):
        raise ValueError("Feature values must be finite numbers.")
    values = pd.DataFrame([[features[name] for name in expected]], columns=expected)
    positive_index = list(model.classes_).index(1)
    score = float(model.predict_proba(values)[0, positive_index])
    threshold = float(metadata["selected_threshold"])
    top_features = metadata.get("feature_importance", [])[:5]
    return {
        "prediction_id": str(uuid.uuid4()),
        "prediction": int(score >= threshold),
        "risk_score": score,
        "score_type": "uncalibrated positive-class model score; not a fraud probability",
        "threshold": threshold,
        "model_id": metadata["model_id"],
        "model_name": metadata["model_name"],
        "dataset_name": metadata["dataset_name"],
        "global_feature_importance": top_features,
        "limitations": metadata["limitations"],
    }
