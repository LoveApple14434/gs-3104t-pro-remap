#!/usr/bin/env python3

from __future__ import annotations

import os
import re
import signal
import subprocess
import sys
from pathlib import Path
from urllib.request import urlopen

import webview


APP_TITLE = "Kbd Drive Remap Editor"
URL_RE = re.compile(r"https?://[^\s]+")


def _extract_url(line: str) -> str | None:
    match = URL_RE.search(line)
    return match.group(0) if match else None


def _shutdown_backend(proc: subprocess.Popen[str], url: str | None) -> None:
    if url:
        try:
            with urlopen(f"{url}api/quit", timeout=1):
                pass
        except Exception:
            pass

    if proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=2)
        except subprocess.TimeoutExpired:
            proc.kill()


def _start_backend(script_path: Path) -> tuple[subprocess.Popen[str], str]:
    proc = subprocess.Popen(
        [sys.executable, str(script_path), "--no-open", "--host", "127.0.0.1", "--port", "0"],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        env={**os.environ, "PYTHONUNBUFFERED": "1"},
    )

    assert proc.stdout is not None
    for line in proc.stdout:
        url = _extract_url(line)
        if url:
            if not url.endswith("/"):
                url = f"{url}/"
            return proc, url

    output = proc.stdout.read() if proc.stdout else ""
    raise RuntimeError(f"无法启动后端服务。\n{output}")


def main() -> int:
    script_path = Path(__file__).resolve().parent / "kbd-drive-config-ui.py"
    if not script_path.exists():
        print(f"找不到后端脚本: {script_path}", file=sys.stderr)
        return 1

    backend_proc: subprocess.Popen[str] | None = None
    backend_url: str | None = None

    try:
        backend_proc, backend_url = _start_backend(script_path)
        webview.create_window(APP_TITLE, backend_url, width=1280, height=860, min_size=(920, 640))
        webview.start()
        return 0
    except Exception as exc:  # noqa: BLE001
        print(str(exc), file=sys.stderr)
        return 1
    finally:
        if backend_proc is not None:
            _shutdown_backend(backend_proc, backend_url)


if __name__ == "__main__":
    signal.signal(signal.SIGINT, signal.SIG_DFL)
    raise SystemExit(main())
