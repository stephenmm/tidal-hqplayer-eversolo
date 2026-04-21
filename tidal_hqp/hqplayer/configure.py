import socket
import subprocess
import time
import xml.etree.ElementTree as ET

from tidal_hqp.config import HQPLAYER_HOST, HQPLAYER_PORT, HQP_EXE, HQP_SETTINGS_XML


def close_and_wait(timeout: float = 8.0) -> bool:
    """Quit HQPlayer gracefully, fall back to taskkill. Returns True when closed."""
    # Try graceful quit (HQPlayer may close before replying, hence broad except)
    try:
        _xml_send("<Quit />", timeout=2)
    except Exception:
        pass

    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            socket.create_connection((HQPLAYER_HOST, HQPLAYER_PORT), timeout=0.5).close()
            time.sleep(0.5)
        except OSError:
            return True

    subprocess.run(["taskkill", "/IM", "HQPlayer5Desktop.exe", "/F"], capture_output=True)
    time.sleep(2)
    try:
        socket.create_connection((HQPLAYER_HOST, HQPLAYER_PORT), timeout=0.5).close()
        return False
    except OSError:
        return True


def launch() -> None:
    """Launch HQPlayer Desktop in the background if the executable exists."""
    if HQP_EXE.exists():
        subprocess.Popen([str(HQP_EXE)], creationflags=subprocess.DETACHED_PROCESS)
        time.sleep(3)


def patch_settings(*, samplerate: int | None = None, period_time: int | None = None) -> dict:
    """Edit settings.xml on disk and return the new values. HQPlayer must be closed first."""
    tree = ET.parse(HQP_SETTINGS_XML)
    root = tree.getroot()
    engine   = root.find("engine")
    defaults = engine.find("defaults") if engine is not None else None
    network  = engine.find("network")  if engine is not None else None

    if samplerate is not None and defaults is not None:
        defaults.set("samplerate", str(samplerate))
    if period_time is not None and network is not None:
        network.set("period_time", str(period_time))

    tree.write(HQP_SETTINGS_XML, encoding="utf-8", xml_declaration=True)

    return {
        "samplerate": defaults.get("samplerate") if defaults is not None else None,
        "period_time": network.get("period_time")  if network is not None else None,
    }


def read_settings() -> dict:
    """Return current samplerate and period_time from settings.xml."""
    tree = ET.parse(HQP_SETTINGS_XML)
    root = tree.getroot()
    engine   = root.find("engine")
    defaults = engine.find("defaults") if engine is not None else None
    network  = engine.find("network")  if engine is not None else None
    return {
        "samplerate": defaults.get("samplerate") if defaults is not None else None,
        "period_time": network.get("period_time")  if network is not None else None,
        "adaptive_rate": engine.get("adaptive_rate") if engine is not None else None,
    }


# ── Internal ─────────────────────────────────────────────────────────────────

def _xml_send(xml: str, timeout: float = 5.0) -> str:
    header = '<?xml version="1.0" encoding="UTF-8"?>'
    with socket.create_connection((HQPLAYER_HOST, HQPLAYER_PORT), timeout=timeout) as sock:
        sock.sendall((header + xml).encode("utf-8"))
        sock.shutdown(socket.SHUT_WR)
        chunks: list[bytes] = []
        while True:
            chunk = sock.recv(4096)
            if not chunk:
                break
            chunks.append(chunk)
        return b"".join(chunks).decode("utf-8", errors="replace")
