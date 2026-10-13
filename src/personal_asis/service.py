"""Mac user launchd integration: indexing only, no inbound listener."""

import os
from pathlib import Path
import plistlib
import signal
import subprocess
import sys
import time

from .config import load_config
from .index import Index


LABEL = "local.personal-asis.mac"


def daemon(home: Path, emit, interval=21600, tick=30):
    stop = False
    def shutdown(*_):
        nonlocal stop
        stop = True
    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)
    last_wall, last_mono = time.time(), time.monotonic()
    deadline = 0
    config_stamp = None
    while not stop:
        wall, mono = time.time(), time.monotonic()
        # Both elapsed gap and wall/monotonic divergence catch macOS sleep/wake.
        wake = wall - last_wall > tick * 3 or abs((wall - last_wall) - (mono - last_mono)) > tick * 2
        last_wall, last_mono = wall, mono
        try:
            config_path = home / "sources.yaml"
            stamp = config_path.stat().st_mtime_ns
            if mono >= deadline or wake or stamp != config_stamp:
                config = load_config(config_path)
                with Index(home / "index.sqlite3", config) as index:
                    report = index.reconcile()
                emit({"event": "reconcile", **report})
                unavailable = any(s["status"] != "ready" for s in report["sources"])
                deadline = time.monotonic() + (60 if unavailable else interval)
                config_stamp = stamp
        except (OSError, ValueError) as exc:
            emit({"event": "local_error", "error_type": type(exc).__name__})
            deadline = time.monotonic() + 60
        # Short sleeps permit prompt shutdown, no filesystem watcher.
        for _ in range(tick):
            if stop:
                break
            time.sleep(1)


def install(home: Path):
    if sys.platform != "darwin":
        raise ValueError("launchd 安装仅适用于 macOS")
    load_config(home / "sources.yaml")
    home.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(home, 0o700)
    launchagents = Path.home() / "Library" / "LaunchAgents"
    launchagents.mkdir(parents=True, exist_ok=True)
    path = launchagents / f"{LABEL}.plist"
    for name in ("service.stdout.log", "service.stderr.log"):
        log = home / name
        log.touch(mode=0o600, exist_ok=True)
        os.chmod(log, 0o600)
    source_path = str(Path(__file__).resolve().parents[1])
    spec = {
        "Label": LABEL,
        "ProgramArguments": [sys.executable, "-m", "personal_asis", "--home", str(home), "daemon"],
        "EnvironmentVariables": {"PYTHONPATH": source_path, "PYTHONUNBUFFERED": "1"},
        "RunAtLoad": True,
        "KeepAlive": True,
        "ThrottleInterval": 60,
        "ProcessType": "Background",
        "Umask": 0o077,
        "StandardOutPath": str(home / "service.stdout.log"),
        "StandardErrorPath": str(home / "service.stderr.log"),
    }
    domain = f"gui/{os.getuid()}"
    subprocess.run(["launchctl", "bootout", f"{domain}/{LABEL}"], capture_output=True)
    with path.open("wb") as handle:
        plistlib.dump(spec, handle)
    os.chmod(path, 0o600)
    # launchd may finish a bootout asynchronously and briefly reject bootstrap
    # with exit code 5. Retry only that transient result, with a finite bound.
    for attempt in range(5):
        process = subprocess.run(["launchctl", "bootstrap", domain, str(path)], capture_output=True)
        if process.returncode == 0:
            break
        if process.returncode != 5 or attempt == 4:
            process.check_returncode()
        time.sleep(1)
    return {"label": LABEL, "plist": str(path), "home": str(home)}


def uninstall():
    path = Path.home() / "Library" / "LaunchAgents" / f"{LABEL}.plist"
    subprocess.run(["launchctl", "bootout", f"gui/{os.getuid()}/{LABEL}"], capture_output=True)
    path.unlink(missing_ok=True)
    return {"label": LABEL, "uninstalled": True, "local_data_retained": True}
