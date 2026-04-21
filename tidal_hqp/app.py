from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from tidal_hqp.hqplayer.client import hqp_status
from tidal_hqp.hqplayer_routes import router as hqp_router
from tidal_hqp.playback.queue_routes import router as queue_router
from tidal_hqp.playback.routes import router as playback_router
from tidal_hqp.streaming.proxy import router as stream_router
from tidal_hqp.tidal.routes import router as tidal_router
from tidal_hqp.tidal.session import load_token
import tidal_hqp.tidal.session as _ts


@asynccontextmanager
async def lifespan(app: FastAPI):
    if load_token():
        print(f"[tidal] Restored session for {_ts.session.user.email}")
    else:
        print("[tidal] No saved session — call POST /auth/login to authenticate")
    yield


app = FastAPI(title="tidal-hqp", lifespan=lifespan)

app.include_router(tidal_router)
app.include_router(playback_router)
app.include_router(queue_router)
app.include_router(stream_router)
app.include_router(hqp_router)

app.mount("/static", StaticFiles(directory="static"), name="static")


@app.get("/status")
def status():
    hqp: dict = {}
    try:
        hqp = hqp_status()
    except HTTPException:
        hqp = {"error": "HQPlayer not reachable"}
    return {
        "tidal_logged_in": _ts.session.check_login(),
        "hqplayer": hqp,
    }


@app.get("/")
def root():
    return FileResponse("static/index.html")
