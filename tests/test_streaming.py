"""Tests for the streaming proxy — Range handling, wait-for-data, 404 guard."""
import pytest


def test_stream_no_active_returns_404(client):
    resp = client.get("/stream/99")
    assert resp.status_code == 404
    assert resp.json()["detail"] == "No active stream"


def test_stream_head_returns_200_with_headers(client, active_stream):
    resp = client.head("/stream/42")
    assert resp.status_code == 200
    assert resp.headers["accept-ranges"] == "bytes"
    assert resp.headers["content-length"] == "100000"
    assert resp.headers["content-type"] == "audio/flac"


def test_stream_full_get_returns_all_bytes(client, active_stream):
    resp = client.get("/stream/42")
    assert resp.status_code == 200
    assert len(resp.content) == 100_000


def test_stream_range_request_returns_206(client, active_stream):
    resp = client.get("/stream/42", headers={"Range": "bytes=0-999"})
    assert resp.status_code == 206
    assert resp.headers["content-range"] == "bytes 0-999/100000"
    assert resp.headers["content-length"] == "1000"
    assert len(resp.content) == 1000


def test_stream_range_mid_file(client, active_stream):
    resp = client.get("/stream/42", headers={"Range": "bytes=50000-50099"})
    assert resp.status_code == 206
    assert len(resp.content) == 100
    assert resp.headers["content-range"] == "bytes 50000-50099/100000"


def test_stream_open_ended_range(client, active_stream):
    resp = client.get("/stream/42", headers={"Range": "bytes=99000-"})
    assert resp.status_code == 206
    assert len(resp.content) == 1000  # 100000 - 99000


def test_stream_parse_range_invalid_falls_back_to_200(client, active_stream):
    resp = client.get("/stream/42", headers={"Range": "bytes=garbage"})
    assert resp.status_code == 200
