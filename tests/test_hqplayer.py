"""Tests for the HQPlayer TCP XML client (no real socket needed)."""
import socket
import xml.etree.ElementTree as ET
from unittest.mock import MagicMock, patch

import pytest

from tidal_hqp.hqplayer.client import hqp_get_filters, hqp_send, hqp_status


def _fake_socket_ctx(response: bytes):
    """Context manager that returns a mock socket yielding response then EOF."""
    mock_sock = MagicMock()
    mock_sock.recv.side_effect = [response, b""]
    mock_sock.__enter__ = lambda s: mock_sock
    mock_sock.__exit__ = MagicMock(return_value=False)
    return mock_sock


@patch("tidal_hqp.hqplayer.client.socket.create_connection")
def test_hqp_send_returns_response(mock_conn):
    payload = b'<?xml version="1.0"?><Status state="2"/>'
    mock_conn.return_value = _fake_socket_ctx(payload)

    result = hqp_send("<Status />")

    assert "state" in result
    mock_conn.assert_called_once()


@patch("tidal_hqp.hqplayer.client.socket.create_connection")
def test_hqp_send_raises_502_on_connection_error(mock_conn):
    mock_conn.side_effect = OSError("refused")

    from fastapi import HTTPException
    with pytest.raises(HTTPException) as exc_info:
        hqp_send("<Status />")

    assert exc_info.value.status_code == 502
    assert "unreachable" in exc_info.value.detail


@patch("tidal_hqp.hqplayer.client.socket.create_connection")
def test_hqp_status_parses_attributes(mock_conn):
    xml = b'<?xml version="1.0"?><Status state="2" input_fill="0.75" process_speed="10.5"/>'
    mock_conn.return_value = _fake_socket_ctx(xml)

    result = hqp_status()

    assert result["state"] == "2"
    assert result["input_fill"] == "0.75"
    assert result["process_speed"] == "10.5"


@patch("tidal_hqp.hqplayer.client.socket.create_connection")
def test_hqp_status_handles_parse_error(mock_conn):
    mock_conn.return_value = _fake_socket_ctx(b"not xml at all")

    result = hqp_status()

    assert "raw" in result


@patch("tidal_hqp.hqplayer.client.socket.create_connection")
def test_hqp_get_filters_returns_list(mock_conn):
    xml = (
        b'<?xml version="1.0"?><GetFilters>'
        b'<FiltersItem index="0" name="none" />'
        b'<FiltersItem index="1" name="IIR" />'
        b"</GetFilters>"
    )
    mock_conn.return_value = _fake_socket_ctx(xml)

    filters = hqp_get_filters()

    assert len(filters) == 2
    assert filters[0]["name"] == "none"
    assert filters[1]["index"] == "1"


@patch("tidal_hqp.hqplayer.client.hqp_send")
def test_hqp_play_url_does_not_block(mock_send):
    """hqp_play_url must return immediately (the send runs in the background)."""
    import time
    from tidal_hqp.hqplayer.client import hqp_play_url

    mock_send.return_value = '<?xml version="1.0"?><PlaylistAdd result="OK"/>'

    t0 = time.monotonic()
    thread = hqp_play_url("http://127.0.0.1:8080/stream/1")
    elapsed = time.monotonic() - t0

    assert elapsed < 0.5, "hqp_play_url must not block"
    thread.join(timeout=5)
    assert not thread.is_alive(), "background send thread must finish"


@patch("tidal_hqp.hqplayer.client.hqp_send")
def test_hqp_play_url_sends_playlistadd_then_play(mock_send):
    """The background thread must queue the URL and then start playback."""
    from tidal_hqp.hqplayer.client import hqp_play_url

    mock_send.return_value = '<?xml version="1.0"?><PlaylistAdd result="OK"/>'
    url = "http://127.0.0.1:8080/stream/42"

    hqp_play_url(url).join(timeout=5)

    sent = [c.args[0] for c in mock_send.call_args_list]
    assert len(sent) == 2, f"expected PlaylistAdd then Play, got {sent}"
    assert sent[0] == f'<PlaylistAdd uri="{url}" queued="0" clear="1"></PlaylistAdd>'
    assert sent[1] == "<Play />"


@patch("tidal_hqp.hqplayer.client.hqp_send")
def test_hqp_play_url_swallows_send_errors(mock_send):
    """A failing PlaylistAdd must not raise out of the background thread."""
    from tidal_hqp.hqplayer.client import hqp_play_url

    mock_send.side_effect = OSError("boom")
    thread = hqp_play_url("http://127.0.0.1:8080/stream/1")
    thread.join(timeout=5)

    assert not thread.is_alive()


@patch("tidal_hqp.hqplayer.client.socket.create_connection")
def test_hqp_send_concatenates_chunked_response(mock_conn):
    """A response split across recv calls must be reassembled in order."""
    mock_sock = MagicMock()
    mock_sock.recv.side_effect = [b'<?xml version="1.0"?><Sta', b'tus state="2"/>', b""]
    mock_sock.__enter__ = lambda s: mock_sock
    mock_sock.__exit__ = MagicMock(return_value=False)
    mock_conn.return_value = mock_sock

    assert hqp_send("<Status />") == '<?xml version="1.0"?><Status state="2"/>'


@patch("tidal_hqp.hqplayer.client.socket.create_connection")
def test_hqp_send_prefixes_xml_header(mock_conn):
    """Every command must go out with the XML declaration HQPlayer expects."""
    mock_conn.return_value = _fake_socket_ctx(b"<Ok/>")

    hqp_send("<Stop />")

    sent = mock_conn.return_value.sendall.call_args[0][0]
    assert sent == b'<?xml version="1.0" encoding="UTF-8"?><Stop />'


@patch("tidal_hqp.hqplayer.client.socket.create_connection")
def test_hqp_get_rates_parses_items(mock_conn):
    from tidal_hqp.hqplayer.client import hqp_get_rates
    xml = (
        b'<?xml version="1.0"?><GetRates>'
        b'<RatesItem index="0" rate="44100" />'
        b'<RatesItem index="1" rate="176400" />'
        b"</GetRates>"
    )
    mock_conn.return_value = _fake_socket_ctx(xml)

    rates = hqp_get_rates()

    assert [r["rate"] for r in rates] == ["44100", "176400"]


@patch("tidal_hqp.hqplayer.client.socket.create_connection")
def test_hqp_get_rates_handles_parse_error(mock_conn):
    from tidal_hqp.hqplayer.client import hqp_get_rates
    mock_conn.return_value = _fake_socket_ctx(b"garbage")
    assert hqp_get_rates() == []


@patch("tidal_hqp.hqplayer.client.socket.create_connection")
def test_hqp_get_filters_handles_parse_error(mock_conn):
    mock_conn.return_value = _fake_socket_ctx(b"garbage")
    assert hqp_get_filters() == []


@patch("tidal_hqp.hqplayer.client.socket.create_connection")
def test_hqp_set_rate_and_filter_emit_expected_commands(mock_conn):
    from tidal_hqp.hqplayer.client import hqp_set_filter, hqp_set_rate

    mock_conn.return_value = _fake_socket_ctx(b"<Ok/>")
    hqp_set_rate(176400)
    assert b'<SetRate value="176400" />' in mock_conn.return_value.sendall.call_args[0][0]

    mock_conn.return_value = _fake_socket_ctx(b"<Ok/>")
    hqp_set_filter(3)
    assert b'<SetFilter value="3" />' in mock_conn.return_value.sendall.call_args[0][0]


@patch("tidal_hqp.hqplayer.client.socket.create_connection")
def test_hqp_stop_emits_stop(mock_conn):
    from tidal_hqp.hqplayer.client import hqp_stop
    mock_conn.return_value = _fake_socket_ctx(b"<Ok/>")

    hqp_stop()

    assert b"<Stop />" in mock_conn.return_value.sendall.call_args[0][0]
