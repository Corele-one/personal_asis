"""User launchd/systemd integration: reconciliation and outbound polling."""

import os
from pathlib import Path
import plistlib
import signal
import sqlite3
import subprocess
import sys
import time

from .config import load_config
from .index import Index
from .node import Poller


LABEL = "local.personal-asis.mac"
TUNNEL_LABEL = "local.personal-asis.tunnel"
LINUX_LABEL = "personal-asis.service"
LINUX_TUNNEL_LABEL = "personal-asis-tunnel.service"


def _unit_quote(value):
    value = str(value)
    if any(c in value for c in "\n\r\x00"):
        raise ValueError("服务配置不能包含换行或空字符")
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"').replace("%", "%%").replace("$", "$$") + '"'


def _linux_install(label, argv, environment=()):
    directory = Path.home() / ".config" / "systemd" / "user"
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / label
    spec = ("[Unit]\nDescription=Personal Asis PA0 user service\nStartLimitIntervalSec=0\n\n"
            "[Service]\nType=simple\nUMask=0077\nRestart=always\nRestartSec=30\n"
            + "".join("Environment=" + _unit_quote(e) + "\n" for e in environment)
            + "ExecStart=" + " ".join(_unit_quote(a) for a in argv) + "\n\n"
            "[Install]\nWantedBy=default.target\n")
    path.write_text(spec, encoding="utf-8")
    path.chmod(0o600)
    subprocess.run(["systemctl", "--user", "daemon-reload"], capture_output=True, check=True)
    subprocess.run(["systemctl", "--user", "enable", label], capture_output=True, check=True)
    subprocess.run(["systemctl", "--user", "restart", label], capture_output=True, check=True)
    return {"label": label, "unit": str(path)}


def _linux_uninstall(label):
    subprocess.run(["systemctl", "--user", "disable", "--now", label], capture_output=True, check=True)
    (Path.home() / ".config" / "systemd" / "user" / label).unlink(missing_ok=True)
    subprocess.run(["systemctl", "--user", "daemon-reload"], capture_output=True, check=True)
    return {"label": label, "uninstalled": True, "local_data_retained": True}


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
    poller = None
    connection_stamp = None
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
        except (OSError, ValueError, sqlite3.Error) as exc:
            emit({"event": "local_error", "error_type": type(exc).__name__})
            deadline = time.monotonic() + 60
        try:
            connection_path = home / "coordinator.json"
            if connection_path.exists():
                stamp = connection_path.stat().st_mtime_ns
                if poller is None or stamp != connection_stamp:
                    if poller:
                        poller.close()
                    poller = None
                    poller = Poller(home)
                    connection_stamp = stamp
                event = poller.once()
                # Heartbeats are quiet; log completed work and failure types only.
                if event.get("claimed"):
                    emit(event)
            elif poller:
                poller.close()
                poller = None
                connection_stamp = None
        except (OSError, ValueError, sqlite3.Error, subprocess.SubprocessError) as exc:
            emit({"event": "poll_error", "error_type": type(exc).__name__})
        # Short sleeps permit prompt shutdown, no filesystem watcher.
        for _ in range(tick):
            if stop:
                break
            time.sleep(1)
    if poller:
        poller.close()


def install(home: Path):
    if sys.platform == "linux":
        load_config(home / "sources.yaml")
        home.chmod(0o700)
        result = _linux_install(LINUX_LABEL,
            [sys.executable, "-m", "personal_asis", "--home", str(home), "daemon"],
            [f"PYTHONPATH={Path(__file__).resolve().parents[1]}", "PYTHONUNBUFFERED=1"])
        return {**result, "home": str(home)}
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
    if sys.platform == "linux":
        return _linux_uninstall(LINUX_LABEL)
    path = Path.home() / "Library" / "LaunchAgents" / f"{LABEL}.plist"
    subprocess.run(["launchctl", "bootout", f"gui/{os.getuid()}/{LABEL}"], capture_output=True)
    path.unlink(missing_ok=True)
    return {"label": LABEL, "uninstalled": True, "local_data_retained": True}


def install_tunnel(home: Path, host: str, ssh_port=22, local_port=18765, remote_port=8765):
    import re
    if not re.fullmatch(r"[a-zA-Z0-9_.-]+@[a-zA-Z0-9.-]+", host):
        raise ValueError("host 必须为 user@hostname 或 user@IPv4")
    if any(type(p) is not int or not 1024 <= p <= 65535 for p in (local_port, remote_port)) or not 1 <= ssh_port <= 65535:
        raise ValueError("隧道端口无效")
    if sys.platform == "linux":
        return {**_linux_install(LINUX_TUNNEL_LABEL,
            ["/usr/bin/ssh", "-N", "-T", "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=yes",
             "-o", "ExitOnForwardFailure=yes", "-o", "ConnectTimeout=10",
             "-o", "ServerAliveInterval=15", "-o", "ServerAliveCountMax=3",
             "-L", f"127.0.0.1:{local_port}:127.0.0.1:{remote_port}", "-p", str(ssh_port), host]),
             "local_endpoint": f"http://127.0.0.1:{local_port}"}
    if sys.platform != "darwin":
        raise ValueError("常驻隧道仅支持 macOS／Linux 用户服务")
    home.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(home, 0o700)
    directory = Path.home() / "Library" / "LaunchAgents"
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{TUNNEL_LABEL}.plist"
    for name in ("tunnel.stdout.log", "tunnel.stderr.log"):
        (home / name).touch(mode=0o600, exist_ok=True)
        os.chmod(home / name, 0o600)
    spec = {
        "Label": TUNNEL_LABEL,
        "ProgramArguments": ["/usr/bin/ssh", "-N", "-T", "-o", "BatchMode=yes",
                             "-o", "ExitOnForwardFailure=yes", "-o", "ConnectTimeout=10",
                             "-o", "ServerAliveInterval=15", "-o", "ServerAliveCountMax=3",
                             "-L", f"127.0.0.1:{local_port}:127.0.0.1:{remote_port}",
                             "-p", str(ssh_port), host],
        "RunAtLoad": True, "KeepAlive": True, "ThrottleInterval": 30,
        "ProcessType": "Background", "Umask": 0o077,
        "StandardOutPath": str(home / "tunnel.stdout.log"),
        "StandardErrorPath": str(home / "tunnel.stderr.log"),
    }
    domain = f"gui/{os.getuid()}"
    subprocess.run(["launchctl", "bootout", f"{domain}/{TUNNEL_LABEL}"], capture_output=True)
    with path.open("wb") as handle:
        plistlib.dump(spec, handle)
    os.chmod(path, 0o600)
    for attempt in range(5):
        result = subprocess.run(["launchctl", "bootstrap", domain, str(path)], capture_output=True)
        if result.returncode == 0:
            break
        if result.returncode != 5 or attempt == 4:
            result.check_returncode()
        time.sleep(1)
    return {"label": TUNNEL_LABEL, "local_endpoint": f"http://127.0.0.1:{local_port}"}


def uninstall_tunnel():
    if sys.platform == "linux":
        return _linux_uninstall(LINUX_TUNNEL_LABEL)
    subprocess.run(["launchctl", "bootout", f"gui/{os.getuid()}/{TUNNEL_LABEL}"], capture_output=True)
    (Path.home() / "Library" / "LaunchAgents" / f"{TUNNEL_LABEL}.plist").unlink(missing_ok=True)
    return {"label": TUNNEL_LABEL, "uninstalled": True}
