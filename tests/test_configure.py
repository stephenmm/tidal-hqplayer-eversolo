"""Tests for HQPlayer process control and settings.xml editing."""
import subprocess
import xml.etree.ElementTree as ET
from unittest.mock import MagicMock

import pytest

import tidal_hqp.hqplayer.configure as cfg


SETTINGS = (
    '<?xml version="1.0" encoding="utf-8"?>'
    "<hqplayer>"
    '<engine adaptive_rate="1">'
    '<defaults samplerate="44100" />'
    '<network period_time="250" />'
    "</engine>"
    "</hqplayer>"
)


@pytest.fixture()
def settings_xml(tmp_path, monkeypatch):
    f = tmp_path / "settings.xml"
    f.write_text(SETTINGS)
    monkeypatch.setattr(cfg, "HQP_SETTINGS_XML", f)
    return f


@pytest.fixture()
def no_sleep(monkeypatch):
    monkeypatch.setattr(cfg.time, "sleep", lambda _s: None)


def xml_socket(response: bytes = b"<Ok/>"):
    """A mock socket that yields `response` then EOF, so _xml_send terminates."""
    s = MagicMock()
    s.recv.side_effect = [response, b""]
    s.__enter__ = lambda _self: s
    s.__exit__ = MagicMock(return_value=False)
    return s


@pytest.fixture()
def sock(monkeypatch):
    """Control what socket.create_connection does inside configure.py."""
    def install(side_effect):
        m = MagicMock(side_effect=side_effect)
        monkeypatch.setattr(cfg.socket, "create_connection", m)
        return m
    return install


@pytest.fixture()
def clock(monkeypatch):
    """Drive close_and_wait's deadline deterministically."""
    def install(times):
        it = iter(times)
        monkeypatch.setattr(cfg.time, "time", lambda: next(it))
    return install


# ── read_settings ────────────────────────────────────────────────────────────

def test_read_settings_returns_current_values(settings_xml):
    assert cfg.read_settings() == {
        "samplerate": "44100", "period_time": "250", "adaptive_rate": "1",
    }


def test_read_settings_tolerates_a_missing_engine_section(settings_xml):
    settings_xml.write_text('<?xml version="1.0"?><hqplayer />')
    assert cfg.read_settings() == {
        "samplerate": None, "period_time": None, "adaptive_rate": None,
    }


# ── patch_settings ───────────────────────────────────────────────────────────

def test_patch_settings_writes_both_values(settings_xml):
    result = cfg.patch_settings(samplerate=705600, period_time=50000)

    assert result == {"samplerate": "705600", "period_time": "50000"}
    root = ET.parse(settings_xml).getroot()
    assert root.find("engine/defaults").get("samplerate") == "705600"
    assert root.find("engine/network").get("period_time") == "50000"


def test_patch_settings_leaves_omitted_values_untouched(settings_xml):
    result = cfg.patch_settings(samplerate=176400)

    assert result["period_time"] == "250", "period_time must be preserved"
    assert ET.parse(settings_xml).getroot().find("engine/network").get("period_time") == "250"


def test_patch_settings_with_no_arguments_is_a_read(settings_xml):
    assert cfg.patch_settings() == {"samplerate": "44100", "period_time": "250"}


def test_patch_settings_preserves_unrelated_attributes(settings_xml):
    cfg.patch_settings(samplerate=192000)
    assert ET.parse(settings_xml).getroot().find("engine").get("adaptive_rate") == "1"


def test_patch_settings_tolerates_a_missing_engine_section(settings_xml):
    settings_xml.write_text('<?xml version="1.0"?><hqplayer />')
    assert cfg.patch_settings(samplerate=192000) == {"samplerate": None, "period_time": None}


# ── close_and_wait ───────────────────────────────────────────────────────────
#
# Call 1 of create_connection is always the graceful <Quit />; the calls after
# it are the "is the port still open?" probes.

def test_close_and_wait_returns_true_when_the_port_goes_quiet(sock, no_sleep, monkeypatch):
    """A refused probe means HQPlayer is gone — no taskkill needed."""
    run = MagicMock()
    monkeypatch.setattr(cfg.subprocess, "run", run)
    sock([OSError("refused"), OSError("refused")])

    assert cfg.close_and_wait(timeout=1) is True
    run.assert_not_called()


def test_close_and_wait_falls_back_to_taskkill(sock, no_sleep, clock, monkeypatch):
    """A port still open at the deadline must escalate to taskkill."""
    run = MagicMock()
    monkeypatch.setattr(cfg.subprocess, "run", run)
    # Quit answered, one probe still open, then the deadline passes, then the
    # post-taskkill probe is refused.
    sock([xml_socket(), MagicMock(), OSError("refused")])
    clock([0, 1, 100])

    assert cfg.close_and_wait(timeout=8) is True

    run.assert_called_once()
    assert run.call_args[0][0][:2] == ["taskkill", "/IM"]


def test_close_and_wait_returns_false_when_taskkill_fails(sock, no_sleep, monkeypatch):
    """Still reachable after taskkill — the caller must not patch settings."""
    monkeypatch.setattr(cfg.subprocess, "run", MagicMock())
    # timeout=0 skips the wait loop; the post-taskkill probe still connects.
    sock([OSError("refused"), MagicMock()])

    assert cfg.close_and_wait(timeout=0) is False


def test_close_and_wait_survives_a_failing_quit(sock, no_sleep, monkeypatch):
    """HQPlayer often closes before replying to Quit; that must not raise."""
    monkeypatch.setattr(cfg.subprocess, "run", MagicMock())
    sock(OSError("refused"))

    assert cfg.close_and_wait(timeout=1) is True


# ── launch ───────────────────────────────────────────────────────────────────

def test_launch_starts_the_executable_when_it_exists(tmp_path, monkeypatch, no_sleep):
    exe = tmp_path / "HQPlayer5Desktop.exe"
    exe.write_text("")
    monkeypatch.setattr(cfg, "HQP_EXE", exe)
    # Stub the whole module: launch() uses subprocess.DETACHED_PROCESS, which
    # only exists on Windows, and CI runs Linux.
    sp = MagicMock()
    monkeypatch.setattr(cfg, "subprocess", sp)

    cfg.launch()

    sp.Popen.assert_called_once()
    assert sp.Popen.call_args[0][0] == [str(exe)]
    assert sp.Popen.call_args.kwargs["creationflags"] is sp.DETACHED_PROCESS


def test_launch_is_a_noop_when_the_executable_is_missing(tmp_path, monkeypatch, no_sleep):
    monkeypatch.setattr(cfg, "HQP_EXE", tmp_path / "nope.exe")
    sp = MagicMock()
    monkeypatch.setattr(cfg, "subprocess", sp)

    cfg.launch()

    sp.Popen.assert_not_called()


# ── _xml_send ────────────────────────────────────────────────────────────────

def test_xml_send_prefixes_the_header_and_reads_to_eof(sock):
    mock_sock = xml_socket(b"<Ok/>")
    sock(None).return_value = mock_sock

    assert cfg._xml_send("<Quit />") == "<Ok/>"
    assert mock_sock.sendall.call_args[0][0] == b'<?xml version="1.0" encoding="UTF-8"?><Quit />'
