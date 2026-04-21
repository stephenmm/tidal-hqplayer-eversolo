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
def test_hqp_play_url_spawns_thread(mock_send):
    """hqp_play_url must return immediately (thread fires in background)."""
    import time
    from tidal_hqp.hqplayer.client import hqp_play_url

    mock_send.return_value = '<?xml version="1.0"?><PlaylistAdd result="OK"/>'

    t0 = time.monotonic()
    hqp_play_url("http://127.0.0.1:8080/stream/1")
    elapsed = time.monotonic() - t0

    assert elapsed < 0.5, "hqp_play_url must not block"
