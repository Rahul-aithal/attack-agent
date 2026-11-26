# /// script
# requires-python = ">=3.10"
# dependencies = ["psutil>=5.9"]
# ///
"""Report this machine's resources to the Attack Agent dashboard.

Run on EVERY laptop (model nodes and the server). Only `uv` is needed; it fetches Python and
psutil by itself:

    uv run scripts/node_monitor.py --server http://10.170.208.9:8000 --token <admin token> --name windows

Windows without the repo: download just this file and run the same command in PowerShell.

Every --interval seconds it POSTs CPU, RAM, swap, battery, network, NVIDIA GPU (utilisation,
VRAM, temperature, power — via nvidia-smi when present) and the models Ollama currently has
loaded (with how much of each sits in GPU memory) to <server>/telemetry. Nothing else is sent.
"""

from __future__ import annotations

import argparse
import json
import platform
import shutil
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request

import psutil


def gpu_stats() -> list[dict]:
    exe = shutil.which("nvidia-smi")
    if not exe:
        return []
    fields = "name,utilization.gpu,memory.used,memory.total,temperature.gpu,power.draw"
    try:
        out = subprocess.run(
            [exe, f"--query-gpu={fields}", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=5, check=True,
        ).stdout
    except Exception:
        return []
    gpus = []
    for line in out.strip().splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) < 6:
            continue

        def num(v: str) -> float | None:
            try:
                return float(v)
            except ValueError:
                return None

        gpus.append({
            "name": parts[0],
            "util_pct": num(parts[1]),
            "vram_used_mb": num(parts[2]),
            "vram_total_mb": num(parts[3]),
            "temp_c": num(parts[4]),
            "power_w": num(parts[5]),
        })
    return gpus


def ollama_models(url: str) -> dict:
    try:
        with urllib.request.urlopen(f"{url}/api/ps", timeout=3) as resp:
            data = json.load(resp)
    except Exception:
        return {"reachable": False, "models": []}
    models = []
    for m in data.get("models", []):
        size = m.get("size") or 0
        vram = m.get("size_vram") or 0
        models.append({
            "name": m.get("name"),
            "size_mb": round(size / 2**20),
            "vram_mb": round(vram / 2**20),
            "gpu_pct": round(100 * vram / size) if size else 0,
            "context": m.get("context_length"),
        })
    return {"reachable": True, "models": models}


def cpu_temp() -> float | None:
    try:
        temps = psutil.sensors_temperatures()  # Linux only
    except (AttributeError, OSError):
        return None
    for key in ("coretemp", "k10temp", "zenpower", "acpitz", "cpu_thermal"):
        if temps.get(key):
            return max(t.current for t in temps[key])
    return None


def snapshot(name: str, ollama_url: str, net_prev: tuple[float, int, int]) -> tuple[dict, tuple]:
    vm = psutil.virtual_memory()
    sw = psutil.swap_memory()
    battery = None
    try:
        b = psutil.sensors_battery()
        if b:
            battery = {"percent": round(b.percent), "plugged": bool(b.power_plugged)}
    except Exception:
        pass
    net = psutil.net_io_counters()
    now = time.monotonic()
    t0, sent0, recv0 = net_prev
    dt = max(1e-3, now - t0)
    report = {
        "name": name,
        "hostname": socket.gethostname(),
        "os": f"{platform.system()} {platform.release()}",
        "cpu_pct": psutil.cpu_percent(interval=None),
        "cpu_count": psutil.cpu_count(),
        "cpu_temp_c": cpu_temp(),
        "ram_used_mb": round((vm.total - vm.available) / 2**20),
        "ram_total_mb": round(vm.total / 2**20),
        "swap_used_mb": round(sw.used / 2**20),
        "battery": battery,
        "net_up_kbps": round((net.bytes_sent - sent0) * 8 / 1000 / dt, 1),
        "net_down_kbps": round((net.bytes_recv - recv0) * 8 / 1000 / dt, 1),
        "gpus": gpu_stats(),
        "ollama": ollama_models(ollama_url),
    }
    return report, (now, net.bytes_sent, net.bytes_recv)


def post(server: str, token: str, report: dict) -> None:
    req = urllib.request.Request(
        f"{server.rstrip('/')}/telemetry",
        data=json.dumps(report).encode(),
        headers={"Content-Type": "application/json", "X-Admin-Token": token},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=5) as resp:
        resp.read()


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--server", required=True, help="e.g. http://10.170.208.9:8000")
    ap.add_argument("--token", required=True, help="admin token printed by serve.sh")
    ap.add_argument("--name", default=socket.gethostname(), help="label shown on the dashboard")
    ap.add_argument("--interval", type=float, default=2.0, help="seconds between reports")
    ap.add_argument("--ollama", default="http://localhost:11434", help="local Ollama URL")
    args = ap.parse_args()

    psutil.cpu_percent(interval=None)  # prime the CPU counter
    net = psutil.net_io_counters()
    prev = (time.monotonic(), net.bytes_sent, net.bytes_recv)
    print(f"reporting '{args.name}' to {args.server} every {args.interval}s (Ctrl+C to stop)")
    failures = 0
    while True:
        time.sleep(args.interval)
        report, prev = snapshot(args.name, args.ollama, prev)
        try:
            post(args.server, args.token, report)
            if failures:
                print("connected again")
            failures = 0
        except urllib.error.HTTPError as exc:
            if exc.code == 401:
                sys.exit("token rejected — copy the current admin token from the server terminal")
            failures += 1
        except Exception as exc:
            failures += 1
            if failures in (1, 10) or failures % 60 == 0:
                print(f"cannot reach {args.server} ({exc}); retrying…")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
