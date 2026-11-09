#!/usr/bin/env python3
"""Install a pinned official Alma release, without touching Chat or user data.

Run as root on the authorized VPS. Does not start or enable the service;
inspect/configure before activation. Re-running never replaces live data or changes
the version of a running service.
"""
import argparse
import hashlib
from pathlib import Path
import pwd
import shutil
import subprocess
import tarfile
import tempfile

VERSION = "0.4.530"
SHA256 = "05ca4bccddf1c96cd528ae6bd0a20495c73346eeb1b2208646750918069eee49"
PREFIX = f"alma-server-{VERSION}-linux-x64"
ROOT = Path("/opt/alma-work")


def run(*args):
    return subprocess.run(args, check=True, capture_output=True, text=True)


def install(archive, unit):
    if run("id", "-u").stdout.strip() != "0":
        raise SystemExit("root_required")
    if run("uname", "-m").stdout.strip() != "x86_64":
        raise SystemExit("unsupported_architecture")
    with archive.open("rb") as payload:
        if hashlib.file_digest(payload, "sha256").hexdigest() != SHA256:
            raise SystemExit("archive_digest_mismatch")
    runner = unit.with_name("run-alma-work.py")
    if not runner.is_file():
        raise SystemExit("sanitized_runner_required")
    if subprocess.run(["systemctl", "is-active", "--quiet", "alma-work"]).returncode == 0:
        raise SystemExit("stop_work_before_installing")
    try:
        account = pwd.getpwnam("alma-work")
    except KeyError:
        run("useradd", "--system", "--user-group", "--home-dir", "/var/lib/alma-work",
            "--shell", "/usr/sbin/nologin", "alma-work")
        account = pwd.getpwnam("alma-work")
    if account.pw_dir != "/var/lib/alma-work" or account.pw_shell != "/usr/sbin/nologin":
        raise SystemExit("unexpected_work_identity")
    for directory in (Path("/var/lib/alma-work"), Path("/srv/alma-work")):
        directory.mkdir(mode=0o700, exist_ok=True)
        if directory.is_symlink():
            raise SystemExit("symlink_directory_refused")
        directory.chmod(0o700)
        shutil.chown(directory, user="alma-work", group="alma-work")
    instructions = unit.with_name("alma-work-AGENTS.md")
    if instructions.is_file():
        target = Path("/srv/alma-work/AGENTS.md")
        try:
            with target.open("x") as output:
                output.write(instructions.read_text())
        except FileExistsError:
            pass  # Preserve any user-maintained workspace instructions.
        else:
            target.chmod(0o600)
            shutil.chown(target, user="alma-work", group="alma-work")
    releases = ROOT / "releases"
    releases.mkdir(parents=True, exist_ok=True)
    release = releases / PREFIX
    if not release.exists():
        # The official digest is checked before extracting; data filtering also
        # rejects absolute paths, external links and special device members.
        with tempfile.TemporaryDirectory(prefix=".install-", dir=releases) as temp:
            with tarfile.open(archive) as bundle:
                if any(m.name.split("/")[0] != PREFIX for m in bundle.getmembers()):
                    raise SystemExit("unexpected_archive_root")
                bundle.extractall(temp, filter="data")
            extracted = Path(temp) / PREFIX
            run("chown", "-R", "root:root", str(extracted))
            run("chmod", "-R", "go-w", str(extracted))
            (extracted / ".official-sha256").write_text(SHA256 + "\n")
            extracted.rename(release)
    marker = release / ".official-sha256"
    if marker.exists() and marker.read_text().strip() != SHA256:
        raise SystemExit("release_marker_mismatch")
    if not marker.exists():
        raise SystemExit("untracked_release_refused")
    current = ROOT / "current"
    if current.exists() and not current.is_symlink():
        raise SystemExit("unexpected_current_path")
    if current.is_symlink():
        current.unlink()
    current.symlink_to(release)
    shutil.copyfile(runner, ROOT / "run-alma-work.py")
    (ROOT / "run-alma-work.py").chmod(0o755)
    target = Path("/etc/systemd/system/alma-work.service")
    shutil.copyfile(unit, target)
    target.chmod(0o644)
    run("systemd-analyze", "verify", str(target))
    run("systemctl", "daemon-reload")
    print(f"Installed official Alma {VERSION}; did not start or enable service")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("archive", type=Path)
    parser.add_argument("--unit", type=Path, default=Path(__file__).with_name("alma-work.service"))
    args = parser.parse_args()
    install(args.archive, args.unit)
