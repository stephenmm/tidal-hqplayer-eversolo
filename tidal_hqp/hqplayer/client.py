import socket
import threading
import time
import xml.etree.ElementTree as ET

from fastapi import HTTPException

from tidal_hqp.config import HQPLAYER_HOST, HQPLAYER_PORT

_XML_HEADER = '<?xml version="1.0" encoding="UTF-8"?>'


def hqp_send(xml: str, timeout: float = 5.0) -> str:
    """Send one XML command to HQPlayer over TCP and return the response."""
    try:
        with socket.create_connection((HQPLAYER_HOST, HQPLAYER_PORT), timeout=timeout) as sock:
            sock.sendall((_XML_HEADER + xml).encode("utf-8"))
            sock.shutdown(socket.SHUT_WR)
            chunks: list[bytes] = []
            while True:
                chunk = sock.recv(4096)
                if not chunk:
                    break
                chunks.append(chunk)
            return b"".join(chunks).decode("utf-8", errors="replace")
    except OSError as e:
        raise HTTPException(status_code=502, detail=f"HQPlayer unreachable: {e}")


def hqp_play_url(url: str) -> None:
    """Tell HQPlayer to load and play a URL. Runs in a background thread so the
    server can simultaneously serve the stream that HQPlayer fetches."""
    def _send() -> None:
        try:
            t0 = time.time()
            resp = hqp_send(
                f'<PlaylistAdd uri="{url}" queued="0" clear="1"></PlaylistAdd>',
                timeout=30,
            )
            print(f"[hqp] PlaylistAdd in {time.time()-t0:.2f}s: {resp[:120]!r}", flush=True)
            resp2 = hqp_send("<Play />")
            print(f"[hqp] Play at t+{time.time()-t0:.1f}s: {resp2[:120]!r}", flush=True)
        except Exception as e:
            print(f"[hqp] play error: {e}", flush=True)

    threading.Thread(target=_send, daemon=True).start()


def hqp_stop() -> None:
    hqp_send("<Stop />")


def hqp_status() -> dict:
    text = hqp_send('<Status subscribe="0" />')
    try:
        root = ET.fromstring(text)
        return dict(root.attrib)
    except ET.ParseError:
        return {"raw": text}


def hqp_set_rate(rate: int) -> str:
    return hqp_send(f'<SetRate value="{rate}" />')


def hqp_set_filter(index: int) -> str:
    return hqp_send(f'<SetFilter value="{index}" />')


def hqp_get_filters() -> list[dict]:
    text = hqp_send("<GetFilters />")
    try:
        root = ET.fromstring(text)
        return [item.attrib for item in root.findall("FiltersItem")]
    except ET.ParseError:
        return []


def hqp_get_rates() -> list[dict]:
    text = hqp_send("<GetRates />")
    try:
        root = ET.fromstring(text)
        return [item.attrib for item in root.findall("RatesItem")]
    except ET.ParseError:
        return []
