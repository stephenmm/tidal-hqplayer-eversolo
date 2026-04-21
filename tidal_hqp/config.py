import os
import pathlib
from dotenv import load_dotenv

load_dotenv()

HQPLAYER_HOST: str       = os.getenv("HQPLAYER_HOST", "localhost")
HQPLAYER_PORT: int       = int(os.getenv("HQPLAYER_PORT", "4321"))
TOKEN_FILE: pathlib.Path = pathlib.Path(os.getenv("TOKEN_FILE", "tidal_token.json"))
HQP_EXE: pathlib.Path   = pathlib.Path(os.getenv(
    "HQPLAYER_EXE",
    r"C:\Program Files\Signalyst\HQPlayer 5 Desktop\HQPlayer5Desktop.exe",
))
HQP_SETTINGS_XML: pathlib.Path = (
    pathlib.Path.home() / "AppData/Local/HQPlayer/settings.xml"
)
PROXY_HOST: str = "127.0.0.1"
PROXY_PORT: int = int(os.getenv("PORT", "8080"))
PREBUFFER_BYTES: int = 8 * 1024 * 1024  # 8 MB before handing URL to HQPlayer
