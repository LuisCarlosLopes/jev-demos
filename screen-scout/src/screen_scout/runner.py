"""Roda os testes gerados (pytest-playwright) num subprocesso e resume o resultado."""

import os
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path

from .config import Settings


def run_tests(test_file: Path, settings: Settings, url: str | None = None,
              timeout: float = 300, storage_state: str | None = None) -> dict:
    report_file = test_file.with_suffix(".junit.xml")
    report_file.unlink(missing_ok=True)
    command = [
        sys.executable, "-m", "pytest", str(test_file), "-q", "-p", "no:cacheprovider",
        f"--junitxml={report_file}", "-o", "junit_family=xunit2",
    ]
    if settings.browser_channel in {"msedge", "chrome"}:
        command += ["--browser-channel", settings.browser_channel]
    if not settings.headless:
        command.append("--headed")
    env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
    if url:
        env["SCREEN_SCOUT_URL"] = url
    if storage_state:
        env["SCREEN_SCOUT_STORAGE_STATE"] = storage_state
    started = time.perf_counter()
    try:
        process = subprocess.run(
            command, cwd=test_file.parent, env=env, capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": f"Os testes passaram de {int(timeout)} s.", "tests": []}
    elapsed = round((time.perf_counter() - started) * 1000, 1)
    tests = []
    if report_file.is_file():
        for case in ET.parse(report_file).getroot().iter("testcase"):
            status, message = "passed", ""
            for tag in ("failure", "error", "skipped"):
                node = case.find(tag)
                if node is not None:
                    status = {"failure": "failed", "error": "error", "skipped": "skipped"}[tag]
                    message = (node.get("message") or node.text or "").strip().splitlines()
                    message = message[0][:300] if message else ""
                    break
            # O pytest-playwright parametriza por navegador: "test_x[chromium]".
            tests.append({"name": (case.get("name") or "").split("[")[0], "status": status,
                          "ms": round(float(case.get("time") or 0) * 1000, 1),
                          "message": message})
    summary = {s: sum(1 for t in tests if t["status"] == s)
               for s in ("passed", "failed", "skipped", "error")}
    tail = (process.stdout or process.stderr or "").strip().splitlines()[-15:]
    return {"ok": process.returncode in {0, 1}, "exit_code": process.returncode,
            "ms": elapsed, "summary": summary, "tests": tests, "output": tail}
