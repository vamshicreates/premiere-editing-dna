#!/usr/bin/env python3
"""
Cross-Platform Controller for Adobe Premiere Pro (`scripts/premiere_cli.py`).

Combines two reliable bridges across macOS and Windows:
1. Live CEP HTTP-to-ExtendScript Bridge (`http://127.0.0.1:8088`) auto-started by our
   bundled `com.vamshicreates.premieremcp` CEP extension.
2. Direct Premiere Pro Sequence XML (`xmeml v4`) launcher (`open -a` on macOS /
   `Adobe Premiere Pro.exe` on Windows) so complete multi-track timelines open in
   Premiere Pro even if the CEP panel hasn't been initialized yet.
"""

import argparse
import glob
import json
import os
import platform
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

CEP_BRIDGE_URL = "http://127.0.0.1:8088"


def find_premiere_executable() -> str | None:
    """Locate Adobe Premiere Pro across macOS and Windows."""
    env_path = os.environ.get("PREMIERE_PATH") or os.environ.get("PREMIERE_BIN")
    if env_path and Path(env_path).exists():
        return str(Path(env_path).resolve())

    system = platform.system()
    candidates = []

    if system == "Darwin":
        candidates.extend(sorted(glob.glob("/Applications/Adobe Premiere Pro*/Adobe Premiere Pro*.app"), reverse=True))
        candidates.extend(sorted(glob.glob(str(Path.home() / "Applications/Adobe Premiere Pro*/Adobe Premiere Pro*.app")), reverse=True))
        try:
            out = subprocess.check_output(
                ["mdfind", "kMDItemCFBundleIdentifier == 'com.adobe.PremierePro*'"],
                text=True,
                stderr=subprocess.DEVNULL,
            ).strip()
            for line in out.splitlines():
                p = line.strip()
                if p.endswith(".app") and os.path.exists(p):
                    candidates.append(p)
        except Exception:
            pass

    elif system == "Windows":
        for base in [
            os.environ.get("ProgramFiles", r"C:\Program Files"),
            os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"),
        ]:
            if not base:
                continue
            candidates.extend(
                sorted(glob.glob(os.path.join(base, "Adobe", "Adobe Premiere Pro*", "Adobe Premiere Pro.exe")), reverse=True)
            )

    for c in candidates:
        if c and os.path.exists(c):
            return c
    return shutil.which("Adobe Premiere Pro")


def call_cep_bridge(endpoint: str, method: str = "GET", payload: dict = None, timeout: float = 15.0) -> dict | None:
    """Send a request to the local CEP HTTP bridge on 127.0.0.1:8088."""
    url = f"{CEP_BRIDGE_URL}{endpoint}"
    try:
        data = json.dumps(payload).encode("utf-8") if payload is not None else None
        req = urllib.request.Request(url, data=data, method=method, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8").strip()
            return json.loads(raw) if raw else {"status": "success"}
    except Exception:
        return None


def cmd_status() -> dict:
    ppro_bin = find_premiere_executable()
    cep_ping = call_cep_bridge("/ping", "GET", timeout=3.0)
    return {
        "os": platform.system(),
        "premiere_executable": ppro_bin,
        "cep_bridge_online": cep_ping is not None and cep_ping.get("status") == "success",
        "cep_ping": cep_ping,
        "status": "READY_LIVE_BRIDGE" if cep_ping else ("READY_XML_AND_CEP_INSTALLED" if ppro_bin else "PREMIERE_NOT_FOUND"),
    }


def cmd_inspect_sequence() -> dict:
    res = call_cep_bridge("/inspect-sequence", "GET", timeout=20.0)
    if res:
        return res
    return {
        "status": "CEP_OFFLINE",
        "message": "Live CEP bridge (127.0.0.1:8088) is not active yet. Open Premiere Pro (Window > Extensions > Antigravity Premiere Bridge) or pass exported .mp4/.mov/.xml files to extract_editing_dna.py.",
    }


def cmd_import_into_premiere(file_paths: list[str]) -> dict:
    abs_paths = [str(Path(p).resolve()) for p in file_paths if Path(p).exists()]
    if not abs_paths:
        return {"status": "error", "message": "No valid existing files provided to import."}

    # Try live CEP bridge first
    res = call_cep_bridge("/import", "POST", {"paths": abs_paths}, timeout=30.0)
    if res and res.get("status") in ("success", "partial"):
        res["method"] = "live_cep_import"
        return res

    # Fallback: Open XML / project file directly with Premiere Pro executable
    ppro_bin = find_premiere_executable()
    if ppro_bin:
        primary = abs_paths[0]
        system = platform.system()
        try:
            if system == "Darwin":
                subprocess.Popen(["open", "-a", ppro_bin, primary])
            elif system == "Windows":
                subprocess.Popen([ppro_bin, primary])
            else:
                subprocess.Popen([ppro_bin, primary])
            return {
                "status": "success",
                "method": "os_open_in_premiere",
                "opened_file": primary,
                "premiere_executable": ppro_bin,
            }
        except Exception as exc:
            return {"status": "error", "message": str(exc)}

    return {
        "status": "GENERATED_ONLY",
        "files": abs_paths,
        "message": "Sequence XML generated on disk. Import into Premiere Pro via File > Import.",
    }


def cmd_eval_jsx(code: str) -> dict:
    res = call_cep_bridge("/eval", "POST", {"code": code}, timeout=30.0)
    if res:
        return res
    return {
        "status": "error",
        "message": "Live CEP bridge (127.0.0.1:8088) is not reachable. Ensure Premiere Pro is open.",
    }


def main():
    parser = argparse.ArgumentParser(description="Cross-platform Adobe Premiere Pro CLI controller")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("status", help="Check Premiere Pro installation and live CEP bridge status")
    sub.add_parser("inspect-sequence", help="Inspect the active sequence in Premiere Pro (tracks, cuts, ASL)")

    p_imp = sub.add_parser("import", help="Import FCP7 XML sequence or media files into Premiere Pro")
    p_imp.add_argument("files", nargs="+", help="Paths to .xml, .srt, or media files")

    p_eval = sub.add_parser("eval", help="Execute ExtendScript code inside Premiere Pro via CEP bridge")
    p_eval.add_argument("-c", "--code", help="Inline ExtendScript code")
    p_eval.add_argument("-f", "--file", help="Path to .jsx file")

    args = parser.parse_args()

    if args.cmd == "status":
        print(json.dumps(cmd_status(), indent=2))
    elif args.cmd == "inspect-sequence":
        print(json.dumps(cmd_inspect_sequence(), indent=2))
    elif args.cmd == "import":
        print(json.dumps(cmd_import_into_premiere(args.files), indent=2))
    elif args.cmd == "eval":
        code = Path(args.file).read_text(encoding="utf-8") if args.file else (args.code or sys.stdin.read())
        print(json.dumps(cmd_eval_jsx(code), indent=2))


if __name__ == "__main__":
    main()
