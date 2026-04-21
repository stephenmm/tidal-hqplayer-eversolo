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
    """Close HQPlayer, patch settings.xml, and relaunch it."""
    if not HQP_SETTINGS_XML.exists():
        raise HTTPException(status_code=404, detail="settings.xml not found")

    _set_user_stopped()
    if not close_and_wait():
        raise HTTPException(status_code=500, detail="Could not close HQPlayer")

    result = patch_settings(samplerate=req.samplerate, period_time=req.period_time)
    launch()
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
    return [{"index": r["index"], "rate": r["rate"]} for r in rates if r.get("rate", "0") != "0"]


def _set_user_stopped() -> None:
    try:
        from tidal_hqp.playback.queue import mark_user_stopped
        mark_user_stopped()
    except Exception:
        pass
