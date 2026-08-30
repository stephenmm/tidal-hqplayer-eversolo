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


# ── Serving a download that is still in flight ────────────────────────────────

def _growing_file(path, *, chunks=4, size=1000, delay=0.02):
    """Write `chunks` blocks to `path` over time; returns the writer thread."""
    import threading
    import time

    path.write_bytes(b"A" * size)

    def writer():
        for _ in range(chunks - 1):
            time.sleep(delay)
            with open(path, "ab") as f:
                f.write(b"B" * size)

    t = threading.Thread(target=writer, daemon=True)
    t.start()
    return t


def test_stream_waits_for_bytes_still_being_downloaded(client, tmp_path):
    """The reader must block until the downloader catches up, not truncate."""
    from tidal_hqp.streaming.state import _active, _active_lock

    target = tmp_path / "growing.flac"
    writer = _growing_file(target, chunks=4, size=1000)
    with _active_lock:
        _active["tmp_path"]       = str(target)
        _active["content_length"] = 4000
        _active["dl_thread"]      = writer

    resp = client.get("/stream/42")
    writer.join(timeout=5)

    assert resp.status_code == 200
    assert len(resp.content) == 4000, "stream ended before the download finished"
    assert resp.content == b"A" * 1000 + b"B" * 3000


def test_stream_range_waits_for_bytes_still_being_downloaded(client, tmp_path):
    from tidal_hqp.streaming.state import _active, _active_lock

    target = tmp_path / "growing.flac"
    writer = _growing_file(target, chunks=4, size=1000)
    with _active_lock:
        _active["tmp_path"]       = str(target)
        _active["content_length"] = 4000
        _active["dl_thread"]      = writer

    resp = client.get("/stream/42", headers={"Range": "bytes=500-3499"})
    writer.join(timeout=5)

    assert resp.status_code == 206
    assert len(resp.content) == 3000
    assert resp.headers["content-range"] == "bytes 500-3499/4000"


def test_stream_ends_when_the_download_dies_early(client, tmp_path):
    """A download that stops short must close the stream, not hang forever."""
    from tidal_hqp.streaming.state import _active, _active_lock

    target = tmp_path / "short.flac"
    target.write_bytes(b"A" * 500)
    with _active_lock:
        _active["tmp_path"]       = str(target)
        _active["content_length"] = 100_000   # server promised far more
        _active["dl_thread"]      = None      # ...but the download is over

    resp = client.get("/stream/42")

    assert len(resp.content) == 500


# ── Range parsing ─────────────────────────────────────────────────────────────

def test_stream_head_with_range_returns_206(client, active_stream):
    resp = client.head("/stream/42", headers={"Range": "bytes=0-99"})

    assert resp.status_code == 206
    assert resp.headers["content-range"] == "bytes 0-99/100000"
    assert resp.content == b""


def test_stream_range_without_a_known_length_falls_back_to_200(client, fake_flac):
    from tidal_hqp.streaming.state import _active, _active_lock
    with _active_lock:
        _active["tmp_path"]       = fake_flac
        _active["content_length"] = 0
        _active["dl_thread"]      = None

    resp = client.get("/stream/42", headers={"Range": "bytes=0-99"})

    assert resp.status_code == 200


def test_stream_ignores_a_non_bytes_range_unit(client, active_stream):
    resp = client.get("/stream/42", headers={"Range": "items=0-99"})
    assert resp.status_code == 200


def test_stream_404_when_the_temp_file_was_deleted(client, tmp_path):
    from tidal_hqp.streaming.state import _active, _active_lock
    with _active_lock:
        _active["tmp_path"]       = str(tmp_path / "already-gone.flac")
        _active["content_length"] = 100
        _active["dl_thread"]      = None

    assert client.get("/stream/42").status_code == 404


def test_parse_range_helper():
    from tidal_hqp.streaming.proxy import _parse_range

    assert _parse_range("bytes=0-99", 1000)   == (0, 99, True)
    assert _parse_range("bytes=500-", 1000)   == (500, None, True)
    assert _parse_range("bytes=-", 1000)      == (0, None, True)
    assert _parse_range("", 1000)             == (0, None, False)
    assert _parse_range("bytes=abc", 1000)    == (0, None, False)


def test_stream_tolerates_the_temp_file_vanishing_mid_read(client, tmp_path, monkeypatch):
    """The reader must survive kill_active() unlinking the file underneath it."""
    import tidal_hqp.streaming.proxy as proxy
    from tidal_hqp.streaming.state import _active, _active_lock

    target = tmp_path / "racy.flac"
    target.write_bytes(b"A" * 2000)

    writer = _growing_file(tmp_path / "unused.flac", chunks=1, size=1)

    with _active_lock:
        _active["tmp_path"]       = str(target)
        _active["content_length"] = 2000
        _active["dl_thread"]      = writer

    real_getsize = proxy.os.path.getsize
    calls = {"n": 0}

    def flaky_getsize(path):
        calls["n"] += 1
        if calls["n"] == 1:
            raise OSError("file vanished")
        return real_getsize(path)

    monkeypatch.setattr(proxy.os.path, "getsize", flaky_getsize)

    resp = client.get("/stream/42")

    assert resp.status_code == 200
    assert len(resp.content) == 2000
