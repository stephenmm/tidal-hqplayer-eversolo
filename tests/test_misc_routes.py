"""Tests for the GPU telemetry route and the static index route."""
import subprocess
from unittest.mock import MagicMock

import pytest

import tidal_hqp.gpu_routes as gr


# ── /gpu ─────────────────────────────────────────────────────────────────────

def test_gpu_parses_nvidia_smi_output(client, monkeypatch):
    monkeypatch.setattr(gr.subprocess, "check_output", lambda *a, **k: "42, 17, 63\n")

    assert client.get("/gpu").json() == {"gpu_pct": 42, "mem_pct": 17, "temp_c": 63}


def test_gpu_strips_whitespace_around_values(client, monkeypatch):
    monkeypatch.setattr(gr.subprocess, "check_output", lambda *a, **k: "  0 ,  0 ,  35  \n")

    assert client.get("/gpu").json() == {"gpu_pct": 0, "mem_pct": 0, "temp_c": 35}


def test_gpu_queries_the_expected_fields(client, monkeypatch):
    seen = {}

    def fake(cmd, **kwargs):
        seen["cmd"] = cmd
        seen["kwargs"] = kwargs
        return "1, 2, 3"

    monkeypatch.setattr(gr.subprocess, "check_output", fake)
    client.get("/gpu")

    assert seen["cmd"][0] == "nvidia-smi"
    assert "utilization.gpu" in seen["cmd"][1]
    assert seen["kwargs"]["timeout"] == 3


def test_gpu_reports_a_missing_nvidia_smi(client, monkeypatch):
    monkeypatch.setattr(gr.subprocess, "check_output",
                        MagicMock(side_effect=FileNotFoundError()))

    assert client.get("/gpu").json() == {"error": "nvidia-smi not found"}


def test_gpu_reports_a_timeout(client, monkeypatch):
    monkeypatch.setattr(gr.subprocess, "check_output",
                        MagicMock(side_effect=subprocess.TimeoutExpired("nvidia-smi", 3)))

    body = client.get("/gpu").json()

    assert "error" in body and "gpu_pct" not in body


def test_gpu_reports_unparseable_output(client, monkeypatch):
    """A driver that returns '[N/A]' must not 500 the endpoint."""
    monkeypatch.setattr(gr.subprocess, "check_output", lambda *a, **k: "[N/A], [N/A], [N/A]")

    body = client.get("/gpu").json()

    assert "error" in body


def test_gpu_never_raises(client, monkeypatch):
    monkeypatch.setattr(gr.subprocess, "check_output", MagicMock(side_effect=RuntimeError("boom")))

    resp = client.get("/gpu")

    assert resp.status_code == 200
    assert resp.json()["error"] == "boom"


# ── / ────────────────────────────────────────────────────────────────────────

def test_root_serves_the_web_ui(client):
    resp = client.get("/")

    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]


def test_static_files_are_mounted(client):
    assert client.get("/static/index.html").status_code == 200


# ── /status ──────────────────────────────────────────────────────────────────

def test_status_reports_hqplayer_attributes(client, mock_hqp_send, logged_in_session):
    body = client.get("/status").json()

    assert body["tidal_logged_in"] is True
    assert body["hqplayer"]["state"] == "2"


def test_status_reports_logged_out(client, mock_hqp_send):
    assert client.get("/status").json()["tidal_logged_in"] is False
