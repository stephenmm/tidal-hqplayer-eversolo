"""Entry point — run with: python server.py"""
import uvicorn

if __name__ == "__main__":
    uvicorn.run("tidal_hqp.app:app", host="0.0.0.0", port=8080, reload=False)
