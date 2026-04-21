import subprocess

from fastapi import APIRouter

router = APIRouter()


@router.get("/gpu")
def gpu_status():
    try:
        out = subprocess.check_output(
            [
                "nvidia-smi",
                "--query-gpu=utilization.gpu,utilization.memory,temperature.gpu",
                "--format=csv,noheader,nounits",
            ],
            timeout=3,
            text=True,
        )
        parts = [p.strip() for p in out.strip().split(",")]
        return {
            "gpu_pct": int(parts[0]),
            "mem_pct": int(parts[1]),
            "temp_c":  int(parts[2]),
        }
    except FileNotFoundError:
        return {"error": "nvidia-smi not found"}
    except Exception as e:
        return {"error": str(e)}
