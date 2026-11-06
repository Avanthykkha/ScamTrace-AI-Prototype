import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pandas as pd

from scamtrace.ml import _load_dataset, _metrics, predict


class DatasetValidationTests(unittest.TestCase):
    def test_ulb_label_is_separated_and_unexpected_features_are_rejected(self):
        features = {f"V{index}": [0.0, 1.0] for index in range(1, 29)}
        features["Amount"] = [5.0, 8.0]
        frame = pd.DataFrame({**features, "Class": [0, 1], "review_flag": [0, 1]})
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "ulb.csv"
            frame.to_csv(path, index=False)
            with self.assertRaisesRegex(ValueError, "Unexpected ULB feature schema"):
                _load_dataset(path)

            frame = frame.drop(columns="review_flag")
            frame.to_csv(path, index=False)
            x, y = _load_dataset(path)

        self.assertNotIn("Class", x.columns)
        self.assertEqual(len(x.columns), 29)
        self.assertEqual(y.tolist(), [0, 1])


class EvaluationTests(unittest.TestCase):
    def test_confusion_matrix_metrics_use_the_supplied_test_predictions(self):
        labels = pd.Series([0, 0, 1, 1])
        scores = np.array([0.1, 0.8, 0.9, 0.2])
        metrics = _metrics(labels, scores, threshold=0.5)
        self.assertEqual(
            metrics["confusion_matrix"],
            {"true_negative": 1, "false_positive": 1, "false_negative": 1, "true_positive": 1},
        )
        self.assertEqual(metrics["precision"], 0.5)
        self.assertEqual(metrics["recall"], 0.5)
        self.assertEqual(metrics["f1"], 0.5)
        self.assertEqual(metrics["top_k"], 1)


class InferenceTests(unittest.TestCase):
    def test_inference_uses_metadata_feature_order_and_reports_global_importance(self):
        class FakeModel:
            classes_ = np.array([0, 1])
            received_columns = []

            def predict_proba(self, frame):
                self.received_columns = list(frame.columns)
                return np.array([[0.7, 0.3]])

        model = FakeModel()
        metadata = {
            "dataset_features": ["V2", "V1"],
            "selected_threshold": 0.25,
            "model_id": "test-model",
            "model_name": "test",
            "dataset_name": "ULB test fixture",
            "feature_importance": [{"name": "V1", "importance": 0.8}],
            "limitations": ["Benchmark only."],
        }
        with patch("scamtrace.ml.load_selected_model", return_value=(model, metadata)):
            result = predict({"V1": 1.0, "V2": 2.0})

        self.assertEqual(model.received_columns, ["V2", "V1"])
        self.assertEqual(result["prediction"], 1)
        self.assertEqual(result["risk_score"], 0.3)
        self.assertIn("not a fraud probability", result["score_type"])
        self.assertEqual(result["global_feature_importance"], metadata["feature_importance"])
        self.assertNotIn("feature_relevance", result)

    def test_inference_rejects_nonfinite_values(self):
        metadata = {"dataset_features": ["V1"]}
        with patch("scamtrace.ml.load_selected_model", return_value=(object(), metadata)):
            with self.assertRaisesRegex(ValueError, "finite numbers"):
                predict({"V1": float("nan")})


if __name__ == "__main__":
    unittest.main()