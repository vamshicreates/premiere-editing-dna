#!/usr/bin/env python3
"""
Zero-Dependency Stdio MCP Server for Adobe Premiere Pro (`scripts/premiere_mcp_server.py`).

Implements the Model Context Protocol (JSON-RPC 2.0 over stdio) using 100% Python
standard library so it runs out of the box on Windows and macOS without pip or uv.
"""

import json
import subprocess
import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS_DIR))

from build_premiere_sequence import (  # noqa: E402
    build_sequence_xml,
    detect_speech_segments,
    execute_live_step_by_step_in_premiere,
)
from premiere_cli import call_cep_bridge, cmd_eval_jsx, cmd_import_into_premiere, cmd_inspect_sequence, cmd_status  # noqa: E402

TOOLS = [
    {
        "name": "premiere_status",
        "description": "Check Adobe Premiere Pro installation and live CEP bridge status on macOS or Windows.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "premiere_inspect_sequence",
        "description": "Inspect the currently active sequence in Adobe Premiere Pro (tracks, clip cuts, durations, and Average Shot Length).",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "premiere_extract_editing_dna",
        "description": "Extract Editing DNA (cut pacing, Average Shot Length, hook pacing, aspect ratio, frame rate, silence profile, and track architecture) from a folder of previous approved edits (.mp4, .mov, .xml) or the active Premiere Pro sequence.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "source_dir": {"type": "string", "description": "Directory or file path of previous approved video edits."},
                "state_dir": {"type": "string", "description": "Cache directory (default: .editing-dna)."},
            },
            "required": ["source_dir"],
        },
    },
    {
        "name": "premiere_auto_cut_silence",
        "description": "Scan a raw A-roll video file using ffmpeg silencedetect and return tightened speech cuts with alternating punch-in zoom scales.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "video_path": {"type": "string", "description": "Path to raw A-roll video file."},
                "noise_db": {"type": "number", "description": "Silence threshold in dB (default: -35)."},
                "min_silence_sec": {"type": "number", "description": "Minimum silence duration to cut in seconds (default: 0.30)."},
                "zoom_scale": {"type": "number", "description": "Alternating punch-in scale percentage (default: 112)."},
            },
            "required": ["video_path"],
        },
    },
    {
        "name": "premiere_build_sequence",
        "description": "Compile a declarative timeline_spec.json into a multi-track Premiere Pro sequence (V1 A-Roll, V2 B-Roll, V3 Overlays, A1 Dialogue, A2 SFX, A3 Ducked BGM, Markers, and .srt Captions) and automatically open/import it in Adobe Premiere Pro.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "spec_json_path": {"type": "string", "description": "Path to timeline_spec.json."},
                "open_in_premiere": {"type": "boolean", "description": "Import/open immediately in Premiere Pro (default: true)."},
            },
            "required": ["spec_json_path"],
        },
    },
    {
        "name": "premiere_execute_jsx",
        "description": "Execute custom ExtendScript code inside Adobe Premiere Pro (`app.project` / `qe.project`) via the live CEP bridge.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "code": {"type": "string", "description": "ExtendScript code to execute inside Premiere Pro."}
            },
            "required": ["code"],
        },
    },
]


def handle_tool_call(name: str, arguments: dict) -> dict:
    try:
        if name == "premiere_status":
            res = cmd_status()
        elif name == "premiere_inspect_sequence":
            res = cmd_inspect_sequence()
        elif name == "premiere_extract_editing_dna":
            src = arguments.get("source_dir", ".")
            state = arguments.get("state_dir", ".editing-dna")
            proc = subprocess.run(
                [sys.executable, str(SCRIPTS_DIR / "extract_editing_dna.py"), src, "--state-dir", state],
                capture_output=True,
                text=True,
                timeout=180,
            )
            try:
                res = json.loads(proc.stdout)
            except Exception:
                res = {"status": "completed", "stdout": proc.stdout, "stderr": proc.stderr}
        elif name == "premiere_auto_cut_silence":
            cuts = detect_speech_segments(
                arguments["video_path"],
                noise_db=float(arguments.get("noise_db", -35.0)),
                min_silence_sec=float(arguments.get("min_silence_sec", 0.30)),
                zoom_scale=float(arguments.get("zoom_scale", 112.0)),
            )
            res = {"status": "success", "cutCount": len(cuts), "v1_aroll": cuts}
        elif name == "premiere_build_sequence":
            spec = json.loads(Path(arguments["spec_json_path"]).read_text(encoding="utf-8"))
            res = build_sequence_xml(spec)
            if arguments.get("open_in_premiere", True):
                live_res = execute_live_step_by_step_in_premiere(spec)
                if live_res:
                    res["live_execution"] = live_res
                    if res.get("outputSrt"):
                        call_cep_bridge("/import", "POST", {"paths": [res["outputSrt"]]}, timeout=15.0)
                elif res.get("outputXml"):
                    files = [res["outputXml"]]
                    if res.get("outputSrt"):
                        files.append(res["outputSrt"])
                    res["premiere_import"] = cmd_import_into_premiere(files)
        elif name == "premiere_execute_jsx":
            res = cmd_eval_jsx(arguments["code"])
        else:
            return {"content": [{"type": "text", "text": f"Unknown tool: {name}"}], "isError": True}

        return {"content": [{"type": "text", "text": json.dumps(res, indent=2)}], "isError": res.get("status") == "error"}
    except Exception as exc:
        return {"content": [{"type": "text", "text": json.dumps({"status": "error", "message": str(exc)})}], "isError": True}


def main():
    for raw_line in sys.stdin:
        line = raw_line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except Exception:
            continue

        method = msg.get("method")
        msg_id = msg.get("id")

        if method == "initialize":
            resp = {
                "jsonrpc": "2.0",
                "id": msg_id,
                "result": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {"tools": {}},
                    "serverInfo": {"name": "premiere-editing-dna", "version": "1.0.0"},
                },
            }
            sys.stdout.write(json.dumps(resp) + "\n")
            sys.stdout.flush()
        elif method == "notifications/initialized":
            continue
        elif method == "ping":
            sys.stdout.write(json.dumps({"jsonrpc": "2.0", "id": msg_id, "result": {}}) + "\n")
            sys.stdout.flush()
        elif method == "tools/list":
            sys.stdout.write(json.dumps({"jsonrpc": "2.0", "id": msg_id, "result": {"tools": TOOLS}}) + "\n")
            sys.stdout.flush()
        elif method == "tools/call":
            params = msg.get("params", {})
            tool_res = handle_tool_call(params.get("name", ""), params.get("arguments", {}) or {})
            sys.stdout.write(json.dumps({"jsonrpc": "2.0", "id": msg_id, "result": tool_res}) + "\n")
            sys.stdout.flush()
        elif msg_id is not None:
            sys.stdout.write(
                json.dumps({"jsonrpc": "2.0", "id": msg_id, "error": {"code": -32601, "message": f"Method not found: {method}"}}) + "\n"
            )
            sys.stdout.flush()


if __name__ == "__main__":
    main()
