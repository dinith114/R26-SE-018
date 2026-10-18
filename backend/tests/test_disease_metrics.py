"""The metrics endpoint's numbers come from the saved result files.

The panel asked to SEE the evaluation. What the endpoint reports must be
exactly what the evaluation scripts measured -- a number copied by hand drifts
the first time a model is retrained. So these tests pin:

  * the endpoint reproduces the reported test-set figures from the files
  * a missing result file drops its section instead of failing the request
  * a smoke-test experiment run is never shown as a result
  * reading it needs no sign-in, and loads no model
"""
import json
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.routes import disease_detection
from app.services import disease_service as ds

REAL = ds.COMPONENT / "results" / "extended_metrics" / "metrics_test.json"


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(disease_detection.router, prefix="/api/v1/disease")
    return TestClient(app)


@pytest.mark.skipif(not REAL.exists(), reason="evaluation results not in this checkout")
def test_the_screen_shows_what_the_evaluation_measured(client):
    r = client.get("/api/v1/disease/metrics")           # no sign-in needed
    assert r.status_code == 200
    m = r.json()["metrics"]
    measured = json.loads(REAL.read_text(encoding="utf-8"))
    assert m["disease"]["accuracy"] == measured["accuracy"]
    assert m["disease"]["macro_f1"] == measured["macro_f1"]
    assert m["disease"]["n_images"] == 67
    assert m["disease"]["accuracy"] > m["disease"]["baseline"]["accuracy"]
    assert m["data"]["leakage_check"] == "PASS"
    assert "results/extended_metrics/metrics_test.json" in m["sources"]


def _component(tmp_path, files):
    for rel, content in files.items():
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(content) if not isinstance(content, str) else content,
                     encoding="utf-8")
    return tmp_path


def test_missing_files_drop_their_section_not_the_request(tmp_path, monkeypatch):
    monkeypatch.setattr(ds, "COMPONENT", tmp_path)
    monkeypatch.setattr(ds, "MODELS", tmp_path / "models")
    assert ds.metrics_summary() == {"sources": []}


DISEASE = {
    "n_images": 4, "class_names": ["a", "b"], "accuracy": 0.75, "macro_f1": 0.7,
    "per_class": {}, "confusion_matrix": [[2, 0], [1, 1]],
    "misclassified": [{"file": "b_2.jpg"}],
}


def test_a_near_copy_in_the_test_set_is_shown_with_the_score_without_it(tmp_path, monkeypatch):
    _component(tmp_path, {
        "models/metrics_test.json": DISEASE,
        "results/photo_checks/photo_check_thresholds.json": {
            "near_copies_across_split": [
                {"held_out": "a/a_1.jpg", "part": "test", "train": "a/a_9.jpg", "bits": 2}]},
    })
    monkeypatch.setattr(ds, "COMPONENT", tmp_path)
    monkeypatch.setattr(ds, "MODELS", tmp_path / "models")
    near = ds.metrics_summary()["disease"]["near_copies"]
    # 3 of 4 right; a_1 was right, so without it 2 of 3 are right.
    assert near == {"test_photos": ["a_1.jpg"], "n_without": 3, "accuracy_without": 2 / 3}


def test_a_smoke_test_experiment_run_is_never_shown(tmp_path, monkeypatch):
    row = {"row": "R", "label": "x", "task": "disease", "split": "original",
           "metrics": {"accuracy": 0.3, "macro_f1": 0.2}}
    _component(tmp_path, {
        "results/experiments/report/experiments_summary.json": {"smoke_test": True, "rows": [row]},
    })
    monkeypatch.setattr(ds, "COMPONENT", tmp_path)
    monkeypatch.setattr(ds, "MODELS", tmp_path / "models")
    assert "experiments" not in ds.metrics_summary()

    _component(tmp_path, {
        "results/experiments/report/experiments_summary.json": {"smoke_test": False, "rows": [row]},
    })
    shown = ds.metrics_summary()["experiments"]["rows"]
    assert [r["id"] for r in shown] == ["R"]


def test_reading_the_metrics_loads_no_model(client, monkeypatch):
    def refuse(*_a, **_k):
        raise AssertionError("the metrics endpoint must not load a model")
    monkeypatch.setattr(ds, "_cascade", refuse)
    assert client.get("/api/v1/disease/metrics").status_code == 200
