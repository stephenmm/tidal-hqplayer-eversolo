import threading
import time

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from tidal_hqp.config import HQP_SETTINGS_XML
from tidal_hqp.hqplayer.client import hqp_get_rates, hqp_status
from tidal_hqp.hqplayer.configure import close_and_wait, launch, patch_settings, read_settings

router = APIRouter()


class HQPSettingsRequest(BaseModel):
    samplerate: int | None = None
    period_time: int | None = None


@router.post("/hqplayer/configure")
def hqplayer_configure(req: HQPSettingsRequest):
    """Close HQPlayer, patch settings.xml, relaunch, and resume the current track."""
    if not HQP_SETTINGS_XML.exists():
        raise HTTPException(status_code=404, detail="settings.xml not found")

    resume_index = _current_queue_index()
    _set_user_stopped()
    if not close_and_wait():
        raise HTTPException(status_code=500, detail="Could not close HQPlayer")

    result = patch_settings(samplerate=req.samplerate, period_time=req.period_time)
    launch()

    if resume_index is not None:
        threading.Thread(target=_resume_after_restart, args=(resume_index,), daemon=True).start()

    return {"ok": True, **result}


@router.post("/hqplayer/restart")
def hqplayer_restart():
    """Close and relaunch HQPlayer without changing settings."""
    _set_user_stopped()
    if not close_and_wait():
        raise HTTPException(status_code=500, detail="Could not close HQPlayer")
    launch()
    return {"ok": True}


@router.get("/hqplayer/settings")
def hqplayer_settings():
    if not HQP_SETTINGS_XML.exists():
        raise HTTPException(status_code=404, detail="settings.xml not found")
    return read_settings()


@router.get("/hqplayer/rates")
def hqplayer_rates():
    """Return available output sample rates from the running HQPlayer instance."""
    rates = hqp_get_rates()
    return [{"index": r["index"], "rate": r["rate"]} for r in rates if int(r.get("rate", 0)) > 0]


def _resume_after_restart(index: int) -> None:
    """Wait for HQPlayer to become reachable then replay the current queue track."""
    deadline = time.time() + 30
    while time.time() < deadline:
        time.sleep(1)
        try:
            hqp_status()
            break
        except Exception:
            continue
    else:
        print("[hqp] resume: HQPlayer never became ready", flush=True)
        return

    print(f"[hqp] resuming queue index {index} after restart", flush=True)
    from tidal_hqp.playback.queue import _do_play
    _do_play(index)


def _current_queue_index() -> int | None:
    try:
        from tidal_hqp.playback.queue import get_state
        return get_state()["current_index"]
    except Exception:
        return None


def _set_user_stopped() -> None:
    try:
        from tidal_hqp.playback.queue import mark_user_stopped
        mark_user_stopped()
    except Exception:
        pass
