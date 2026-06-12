#!/usr/bin/env python
"""One-command bootstrap + launcher for OpenX.

Running ``python setup.py`` will, in order:

  1. Create ``service/.venv`` (if missing) and install ``service/requirements.txt``.
  2. Run ``npm install`` in ``dashboard/`` (if missing).
  3. Launch both the service API (``opensocial serve`` on :8765) and the Vite
     dashboard dev server (:5174) as child processes, streaming both logs here
     with ``[service]`` / ``[dashboard]`` prefixes.

Press Ctrl-C once to stop both cleanly.

Steps 1-2 are idempotent: dependencies are only reinstalled when
``requirements.txt`` / ``package.json`` change (tracked by a small stamp file),
so day-to-day this just starts the two servers.

Useful flags::

    python setup.py                # setup (if needed) then run both
    python setup.py --setup-only   # install deps, don't launch anything
    python setup.py --skip-setup   # skip the dependency checks, just run
    python setup.py --reinstall    # force pip + npm install
    python setup.py --no-dashboard # run only the service
    python setup.py --no-service   # run only the dashboard

Stdlib only — no third-party packages needed to run this file itself.
"""

from __future__ import annotations

import argparse
import os
import shutil
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SERVICE_DIR = ROOT / "service"
DASHBOARD_DIR = ROOT / "dashboard"
VENV_DIR = SERVICE_DIR / ".venv"

IS_WINDOWS = os.name == "nt"

# Force UTF-8 so child output (and our own markers) survive a cp1252 console.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

# ANSI colors (disabled when output isn't a TTY).
_COLOR = sys.stdout.isatty() and not os.environ.get("NO_COLOR")


def _c(code: str, text: str) -> str:
    return f"\033[{code}m{text}\033[0m" if _COLOR else text


def info(msg: str) -> None:
    print(_c("36", ">>") + " " + msg, flush=True)


def warn(msg: str) -> None:
    print(_c("33", "!!") + " " + msg, flush=True)


def die(msg: str) -> None:
    print(_c("31", "xx") + " " + msg, file=sys.stderr, flush=True)
    sys.exit(1)


# ---------------------------------------------------------------------------
# Paths into the created venv
# ---------------------------------------------------------------------------

def venv_python() -> Path:
    return VENV_DIR / ("Scripts" if IS_WINDOWS else "bin") / (
        "python.exe" if IS_WINDOWS else "python"
    )


def npm_cmd() -> str:
    """Locate npm; on Windows it's ``npm.cmd``."""
    found = shutil.which("npm")
    if not found:
        die("npm not found on PATH — install Node.js (https://nodejs.org) first.")
    return found


# ---------------------------------------------------------------------------
# Stamp helpers — only reinstall when the dependency manifest changes
# ---------------------------------------------------------------------------

def _stamp_is_fresh(stamp: Path, manifest: Path) -> bool:
    return stamp.exists() and stamp.stat().st_mtime >= manifest.stat().st_mtime


def _touch(stamp: Path) -> None:
    stamp.parent.mkdir(parents=True, exist_ok=True)
    stamp.write_text("ok", encoding="utf-8")


# ---------------------------------------------------------------------------
# Setup steps
# ---------------------------------------------------------------------------

def setup_service(force: bool) -> None:
    reqs = SERVICE_DIR / "requirements.txt"
    if not reqs.exists():
        die(f"missing {reqs}")

    if not venv_python().exists():
        info(f"creating virtualenv at {VENV_DIR.relative_to(ROOT)}")
        subprocess.run([sys.executable, "-m", "venv", str(VENV_DIR)], check=True)
        force = True  # brand-new venv always needs an install

    stamp = VENV_DIR / ".requirements.stamp"
    if not force and _stamp_is_fresh(stamp, reqs):
        info("service deps up to date — skipping pip install")
        return

    info("installing service dependencies (pip)")
    py = str(venv_python())
    subprocess.run([py, "-m", "pip", "install", "--upgrade", "pip"], check=True)
    subprocess.run([py, "-m", "pip", "install", "-r", str(reqs)], check=True)
    _touch(stamp)


def setup_dashboard(force: bool) -> None:
    pkg = DASHBOARD_DIR / "package.json"
    if not pkg.exists():
        die(f"missing {pkg}")

    node_modules = DASHBOARD_DIR / "node_modules"
    stamp = node_modules / ".install.stamp"
    if not force and node_modules.exists() and _stamp_is_fresh(stamp, pkg):
        info("dashboard deps up to date — skipping npm install")
        return

    info("installing dashboard dependencies (npm install)")
    subprocess.run([npm_cmd(), "install"], cwd=str(DASHBOARD_DIR), check=True)
    _touch(stamp)


# ---------------------------------------------------------------------------
# Running both processes
# ---------------------------------------------------------------------------

def _pump(proc: subprocess.Popen, label: str, color: str) -> None:
    """Forward a child's combined output, line by line, with a prefix."""
    prefix = _c(color, f"[{label}]")
    assert proc.stdout is not None
    for raw in iter(proc.stdout.readline, b""):
        line = raw.decode("utf-8", "replace").rstrip("\r\n")
        print(f"{prefix} {line}", flush=True)
    proc.stdout.close()


def _spawn(cmd: list[str], cwd: Path, env: dict | None = None) -> subprocess.Popen:
    kwargs: dict = dict(
        cwd=str(cwd),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        env=env,
    )
    # New process group so we can signal the whole tree on shutdown.
    if IS_WINDOWS:
        kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        kwargs["start_new_session"] = True
    return subprocess.Popen(cmd, **kwargs)


def _terminate(proc: subprocess.Popen, label: str) -> None:
    if proc.poll() is not None:
        return
    try:
        if IS_WINDOWS:
            # taskkill /T kills the whole tree (npm -> node, uvicorn workers).
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        else:
            os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
    except Exception:
        proc.terminate()
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()


def run(run_service: bool, run_dashboard: bool) -> int:
    procs: list[tuple[subprocess.Popen, str]] = []
    threads: list[threading.Thread] = []

    if run_service:
        env = os.environ.copy()
        # Make the package importable without installing it into the venv.
        env["PYTHONPATH"] = str(SERVICE_DIR) + os.pathsep + env.get("PYTHONPATH", "")
        cmd = [str(venv_python()), "-m", "opensocial", "serve", "--verbose"]
        info("starting service API on http://127.0.0.1:8765")
        procs.append((_spawn(cmd, SERVICE_DIR, env), "service"))

    if run_dashboard:
        cmd = [npm_cmd(), "run", "dev"]
        info("starting dashboard on http://127.0.0.1:5174")
        procs.append((_spawn(cmd, DASHBOARD_DIR), "dashboard"))

    if not procs:
        warn("nothing to run (both --no-service and --no-dashboard set)")
        return 0

    colors = {"service": "32", "dashboard": "35"}
    for proc, label in procs:
        t = threading.Thread(
            target=_pump, args=(proc, label, colors.get(label, "37")), daemon=True
        )
        t.start()
        threads.append(t)

    if run_dashboard:
        print()
        info(_c("1", "Dashboard: http://127.0.0.1:5174")
             + "   (Ctrl-C to stop everything)")
        print()

    exit_code = 0
    try:
        # Wait until any child exits, then tear the rest down.
        while True:
            for proc, label in procs:
                code = proc.poll()
                if code is not None:
                    warn(f"{label} exited with code {code} — shutting down the rest")
                    exit_code = code or exit_code
                    raise KeyboardInterrupt
            time.sleep(0.5)
    except KeyboardInterrupt:
        print()
        info("stopping…")
    finally:
        for proc, label in procs:
            _terminate(proc, label)
        for t in threads:
            t.join(timeout=2)
    return exit_code


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Bootstrap and run the OpenX service + dashboard together.",
    )
    parser.add_argument("--setup-only", action="store_true",
                        help="install dependencies, then exit without launching.")
    parser.add_argument("--skip-setup", action="store_true",
                        help="skip dependency checks and launch immediately.")
    parser.add_argument("--reinstall", action="store_true",
                        help="force pip + npm install even if deps look current.")
    parser.add_argument("--no-service", action="store_true",
                        help="don't run the Python service.")
    parser.add_argument("--no-dashboard", action="store_true",
                        help="don't run the React dashboard.")
    args = parser.parse_args()

    if not args.skip_setup:
        if not args.no_service:
            setup_service(force=args.reinstall)
        if not args.no_dashboard:
            setup_dashboard(force=args.reinstall)

    if args.setup_only:
        info("setup complete.")
        return

    code = run(
        run_service=not args.no_service,
        run_dashboard=not args.no_dashboard,
    )
    sys.exit(code)


if __name__ == "__main__":
    main()
