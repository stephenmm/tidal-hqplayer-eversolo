from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from tidal_hqp.config import HQP_SETTINGS_XML
from tidal_hqp.hqplayer.client import hqp_status
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

    if not close_and_wait():
        raise HTTPException(status_code=500, detail="Could not close HQPlayer")

    result = patch_settings(samplerate=req.samplerate, period_time=req.period_time)
    launch()
    return {"ok": True, **result}


@router.get("/hqplayer/settings")
def hqplayer_settings():
    """Return current values from settings.xml (does not require HQPlayer to be running)."""
    if not HQP_SETTINGS_XML.exists():
        raise HTTPException(status_code=404, detail="settings.xml not found")
    return read_settings()
