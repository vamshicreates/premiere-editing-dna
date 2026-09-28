#!/usr/bin/env python3
"""
Zero-Touch Cross-Platform Installer for `premiere-editing-dna` (Windows & macOS).

What this script automates:
1. Locates Adobe Premiere Pro on macOS or Windows.
2. Enables Adobe CEP `PlayerDebugMode = 1` across CSXS.9, CSXS.10, CSXS.11, and CSXS.12
   (via `defaults write` on macOS and `HKCU\\Software\\Adobe\\CSXS.*` on Windows — no admin required).
3. Installs our auto-starting CEP extension (`assets/cep_extension`) into the user's
   Adobe CEP extensions folder so Premiere Pro automatically starts the HTTP bridge on 127.0.0.1:8088.
4. Registers `"premiere-pro"` inside `~/.gemini/config/mcp_config.json`.
"""

import argparse
import json
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = SKILL_ROOT / "scripts"
CEP_SRC = SKILL_ROOT / "assets" / "cep_extension"
MCP_SERVER_SCRIPT = SCRIPTS_DIR / "premiere_mcp_server.py"
sys.path.insert(0, str(SCRIPTS_DIR))

from premiere_cli import cmd_status, find_premiere_executable  # noqa: E402


def enable_cep_debug_and_install_extension() -> dict:
    system = platform.system()
    csxs_versions = ["9", "10", "11", "12"]
    debug_set = False

    if system == "Darwin":
        for v in csxs_versions:
            subprocess.run(
                ["defaults", "write", f"com.adobe.CSXS.{v}", "PlayerDebugMode", "1"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            )
        debug_set = True
        ext_root = Path.home() / "Library" / "Application Support" / "Adobe" / "CEP" / "extensions"
    elif system == "Windows":
        for v in csxs_versions:
            subprocess.run(
                ["reg", "add", rf"HKCU\Software\Adobe\CSXS.{v}", "/v", "PlayerDebugMode", "/t", "REG_SZ", "/d", "1", "/f"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            )
        debug_set = True
        appdata = os.environ.get("APPDATA", str(Path.home() / "AppData" / "Roaming"))
        ext_root = Path(appdata) / "Adobe" / "CEP" / "extensions"
    else:
        ext_root = Path.home() / ".adobe" / "CEP" / "extensions"

    target_ext = ext_root / "com.vamshicreates.premieremcp"
    ext_installed = False
    try:
        ext_root.mkdir(parents=True, exist_ok=True)
        if target_ext.exists():
            shutil.rmtree(target_ext)
        shutil.copytree(CEP_SRC, target_ext)
        ext_installed = True
    except Exception as exc:
        return {"playerDebugModeSet": debug_set, "cepExtensionInstalled": False, "error": str(exc)}

    return {
        "playerDebugModeSet": debug_set,
        "cepExtensionInstalled": ext_installed,
        "cepExtensionPath": str(target_ext),
    }


def update_mcp_config() -> str:
    config_dir = Path.home() / ".gemini" / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    config_file = config_dir / "mcp_config.json"

    data = {"mcpServers": {}}
    if config_file.exists():
        try:
            shutil.copy2(config_file, config_dir / "mcp_config.json.backup")
            data = json.loads(config_file.read_text(encoding="utf-8"))
            if not isinstance(data.get("mcpServers"), dict):
                data["mcpServers"] = {}
        except Exception:
            data = {"mcpServers": {}}

    python_bin = sys.executable or ("python" if platform.system() == "Windows" else "python3")
    data["mcpServers"]["premiere-pro"] = {
        "command": python_bin,
        "args": [str(MCP_SERVER_SCRIPT.resolve())],
    }

    config_file.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return str(config_file)


def main():
    parser = argparse.ArgumentParser(description="Zero-touch setup for Premiere Editing DNA skill & MCP")
    parser.parse_args()

    ppro_bin = find_premiere_executable()
    cep_info = enable_cep_debug_and_install_extension()
    mcp_config_path = update_mcp_config()
    status_info = cmd_status()

    summary = {
        "os": platform.system(),
        "premiere_executable": ppro_bin,
        "cep_setup": cep_info,
        "mcp_config_updated": mcp_config_path,
        "bridge_status": status_info,
    }
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
