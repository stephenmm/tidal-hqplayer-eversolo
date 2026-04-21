import os
import time

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response, StreamingResponse

from tidal_hqp.streaming.state import _active, _active_lock

router = APIRouter()


def _parse_range(header: str, content_length: int) -> tuple[int, int | None, bool]:
    """Return (start, end, is_range). end is None when open-ended."""
    if not header.startswith("bytes="):
        return 0, None, False
    parts = header[6:].split("-")
    try:
        start = int(parts[0]) if parts[0] else 0
        end   = int(parts[1]) if len(parts) > 1 and parts[1] else None
        return start, end, True
    except ValueError:
        return 0, None, False


@router.api_route("/stream/{track_id}", methods=["GET", "HEAD"])
def stream_track(track_id: int, request: Request):
    """Serve the locally-cached FLAC to HQPlayer, with HTTP Range support."""
    with _active_lock:
        tmp_path       = _active.get("tmp_path")
        content_length = _active.get("content_length", 0)
        dl_thread      = _active.get("dl_thread")

    if not tmp_path or not os.path.exists(tmp_path):
        raise HTTPException(status_code=404, detail="No active stream")

    range_header = request.headers.get("Range", "")
    start, end, is_range = _parse_range(range_header, content_length)

    base_headers = {"Content-Type": "audio/flac", "Accept-Ranges": "bytes"}

    if is_range and content_length:
        effective_end = end if end is not None else content_length - 1
        send_len = effective_end - start + 1
        resp_headers = {
            **base_headers,
            "Content-Range":  f"bytes {start}-{effective_end}/{content_length}",
            "Content-Length": str(send_len),
        }
        status = 206
    else:
        resp_headers = dict(base_headers)
        if content_length:
            resp_headers["Content-Length"] = str(content_length)
        status = 200

    print(f"[stream] {request.method} range={range_header!r} start={start} cl={content_length}", flush=True)

    if request.method == "HEAD":
        return Response(status_code=status, headers=resp_headers)

    remaining = (end - start + 1) if (is_range and end is not None) else None

    def generate():
        nonlocal remaining
        with open(tmp_path, "rb") as f:
            f.seek(start)
            while True:
                want = min(65536, remaining) if remaining is not None else 65536
                if want <= 0:
                    break
                read_pos = f.tell()
                dl_done = dl_thread is None or not dl_thread.is_alive()
                while True:
                    try:
                        file_size = os.path.getsize(tmp_path)
                    except OSError:
                        file_size = 0
                    if file_size > read_pos or dl_done:
                        break
                    time.sleep(0.001)
                chunk = f.read(want)
                if chunk:
                    if remaining is not None:
                        remaining -= len(chunk)
                    yield chunk
                elif dl_done:
                    break

    return StreamingResponse(generate(), status_code=status, headers=resp_headers, media_type="audio/flac")
