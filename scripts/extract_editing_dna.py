#!/usr/bin/env python3
"""
Editing DNA Extractor (`scripts/extract_editing_dna.py`) for `premiere-editing-dna`.

Extracts an editor's or brand's Editing DNA from:
1. Active Premiere Pro Sequences (via the live CEP bridge `127.0.0.1:8088`).
2. Existing Premiere Pro / FCP7 XML timelines (`.xml`).
3. Previous approved reference video exports (`.mp4`, `.mov`, `.mkv`, `.webm`):
   - Uses `ffprobe` and `ffmpeg` scene-cut detection (`select='gt(scene,0.28)'`) and
     `silencedetect` to measure exact Average Shot Length (ASL), Hook Pacing (first 5s),
     Cuts Per Minute (CPM), aspect ratio, frame rate, and speech-to-pause ratio.
Caches results into `.editing-dna/raw_editing_scan.json` so the agent synthesizes
`.editing-dna/editing_dna.json` once.
"""

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS_DIR))

from premiere_cli import cmd_inspect_sequence  # noqa: E402

VIDEO_EXTS = {".mp4", ".mov", ".mkv", ".webm", ".m4v"}
XML_EXTS = {".xml"}


def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        # Hash first and last 2MB for speed on large video files
        first = f.read(2 * 1024 * 1024)
        h.update(first)
        try:
            f.seek(max(0, path.stat().st_size - 2 * 1024 * 1024))
            h.update(f.read(2 * 1024 * 1024))
        except Exception:
            pass
    return h.hexdigest()[:16]


def analyze_video_with_ffmpeg(video_path: Path) -> dict:
    """Extract resolution, fps, duration, scene-cut timestamps, ASL, and silence profile via ffprobe/ffmpeg."""
    info = {"file": str(video_path), "name": video_path.name}
    ffprobe = shutil.which("ffprobe") or "/opt/homebrew/bin/ffprobe" or "/usr/local/bin/ffprobe"
    ffmpeg = shutil.which("ffmpeg") or "/opt/homebrew/bin/ffmpeg" or "/usr/local/bin/ffmpeg"

    if os.path.exists(ffprobe) or shutil.which("ffprobe"):
        probe_bin = shutil.which("ffprobe") or ffprobe
        try:
            cmd = [
                probe_bin,
                "-v", "error",
                "-select_streams", "v:0",
                "-show_entries", "stream=width,height,r_frame_rate:format=duration",
                "-of", "json",
                str(video_path),
            ]
            out = json.loads(subprocess.check_output(cmd, text=True, timeout=20))
            stream = (out.get("streams") or [{}])[0]
            fmt = out.get("format") or {}
            w = int(stream.get("width", 1920))
            h = int(stream.get("height", 1080))
            fps_raw = stream.get("r_frame_rate", "30/1")
            if "/" in fps_raw:
                num, den = fps_raw.split("/", 1)
                fps = round(float(num) / max(1.0, float(den)), 3)
            else:
                fps = float(fps_raw)
            dur = round(float(fmt.get("duration", 0.0)), 2)
            info.update({
                "width": w,
                "height": h,
                "aspectRatio": "9:16" if h > w else ("1:1" if w == h else "16:9"),
                "fps": fps,
                "durationSec": dur,
            })
        except Exception as exc:
            info["probe_warning"] = str(exc)

    if (os.path.exists(ffmpeg) or shutil.which("ffmpeg")) and info.get("durationSec", 0) > 0:
        ffmpeg_bin = shutil.which("ffmpeg") or ffmpeg
        scan_dur = min(info["durationSec"], 90.0)  # Cap scan to first 90s for speed
        try:
            cmd = [
                ffmpeg_bin,
                "-hide_banner",
                "-t", str(scan_dur),
                "-i", str(video_path),
                "-vf", "select='gt(scene,0.26)',showinfo",
                "-af", "silencedetect=noise=-35dB:d=0.25",
                "-f", "null",
                "-",
            ]
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
            stderr = proc.stderr or ""

            cut_times = [0.0]
            for m in re.finditer(r"pts_time:([0-9.]+)", stderr):
                t = round(float(m.group(1)), 3)
                if t - cut_times[-1] >= 0.2:
                    cut_times.append(t)
            if scan_dur - cut_times[-1] > 0.2:
                cut_times.append(scan_dur)

            shot_lengths = [round(cut_times[i + 1] - cut_times[i], 3) for i in range(len(cut_times) - 1)]
            hook_shots = [s for i, s in enumerate(shot_lengths) if cut_times[i] < 5.0]

            silences = []
            for sm in re.finditer(r"silence_duration:\s*([0-9.]+)", stderr):
                silences.append(float(sm.group(1)))

            avg_shot = round(sum(shot_lengths) / max(1, len(shot_lengths)), 2)
            hook_asl = round(sum(hook_shots) / max(1, len(hook_shots)), 2) if hook_shots else avg_shot
            cpm = round((len(shot_lengths) / max(1.0, scan_dur)) * 60.0, 1)

            info["pacing"] = {
                "analyzedDurationSec": scan_dur,
                "detectedCuts": len(shot_lengths),
                "averageShotLengthSec": avg_shot,
                "hookAverageShotLengthSec": hook_asl,
                "cutsPerMinute": cpm,
                "silencePausesCount": len(silences),
                "totalSilenceSec": round(sum(silences), 2),
            }
        except Exception as exc:
            info["ffmpeg_warning"] = str(exc)

    return info


def parse_fcp7_xml_sequence(xml_path: Path) -> dict:
    """Extract track layout and shot pacing from an existing Premiere Pro FCP7 .xml timeline."""
    try:
        tree = ET.parse(xml_path)
        root = tree.getroot()
        seq = root.find(".//sequence")
        if seq is None:
            return {"file": str(xml_path), "status": "no_sequence_found"}
        name = seq.findtext("name") or xml_path.stem
        rate_tb = float(seq.findtext(".//rate/timebase") or 30.0)
        v_tracks = seq.findall(".//media/video/track")
        a_tracks = seq.findall(".//media/audio/track")
        v1_durations = []
        if v_tracks:
            for ci in v_tracks[0].findall("clipitem"):
                st = float(ci.findtext("start") or 0)
                en = float(ci.findtext("end") or 0)
                if en > st:
                    v1_durations.append((en - st) / rate_tb)
        asl = round(sum(v1_durations) / max(1, len(v1_durations)), 2)
        return {
            "file": str(xml_path),
            "sequenceName": name,
            "timebaseFps": rate_tb,
            "videoTrackCount": len(v_tracks),
            "audioTrackCount": len(a_tracks),
            "v1ClipCount": len(v1_durations),
            "averageShotLengthSec": asl,
        }
    except Exception as exc:
        return {"file": str(xml_path), "error": str(exc)}


def main():
    parser = argparse.ArgumentParser(description="Extract Editing DNA from reference videos, XML timelines, or live Premiere Pro")
    parser.add_argument("source", nargs="?", default=".", help="Directory or file of previous approved edits")
    parser.add_argument("--state-dir", default=".editing-dna", help="Directory to cache extracted Editing DNA")
    args = parser.parse_args()

    source_path = Path(args.source).resolve()
    state_dir = Path(args.state_dir).resolve()
    state_dir.mkdir(parents=True, exist_ok=True)

    video_files = []
    xml_files = []
    if source_path.is_file():
        if source_path.suffix.lower() in VIDEO_EXTS:
            video_files.append(source_path)
        elif source_path.suffix.lower() in XML_EXTS:
            xml_files.append(source_path)
    else:
        for root, dirs, files in os.walk(source_path):
            dirs[:] = [d for d in dirs if not d.startswith(".") and d not in ("node_modules", "venv", "__pycache__", "output")]
            for fn in sorted(files):
                p = Path(root) / fn
                if p.suffix.lower() in VIDEO_EXTS:
                    video_files.append(p)
                elif p.suffix.lower() in XML_EXTS:
                    xml_files.append(p)

    live_seq = cmd_inspect_sequence()
    has_live = live_seq.get("status") == "success"

    corpus_items = [f"{p.name}:{file_sha256(p)}" for p in (video_files[:8] + xml_files[:8])]
    if has_live:
        corpus_items.append(f"live:{live_seq.get('sequenceName')}:{live_seq.get('totalV1Cuts')}")
    corpus_hash = hashlib.sha256("|".join(corpus_items).encode("utf-8")).hexdigest()[:16]

    raw_scan_file = state_dir / "raw_editing_scan.json"
    dna_file = state_dir / "editing_dna.json"

    if raw_scan_file.exists() and dna_file.exists() and corpus_items:
        try:
            cached = json.loads(raw_scan_file.read_text(encoding="utf-8"))
            if cached.get("corpus_hash") == corpus_hash:
                print(json.dumps({
                    "status": "CACHE_HIT",
                    "corpus_hash": corpus_hash,
                    "editing_dna_file": str(dna_file),
                }, indent=2))
                sys.exit(0)
        except Exception:
            pass

    videos_report = [analyze_video_with_ffmpeg(v) for v in video_files[:6]]
    xmls_report = [parse_fcp7_xml_sequence(x) for x in xml_files[:6]]

    asls = [v["pacing"]["averageShotLengthSec"] for v in videos_report if "pacing" in v and v["pacing"]["averageShotLengthSec"] > 0]
    if has_live and live_seq.get("averageShotLengthSec", 0) > 0:
        asls.append(live_seq["averageShotLengthSec"])
    for xr in xmls_report:
        if xr.get("averageShotLengthSec", 0) > 0:
            asls.append(xr["averageShotLengthSec"])

    overall_asl = round(sum(asls) / max(1, len(asls)), 2) if asls else 2.8

    result = {
        "status": "SCAN_COMPLETED",
        "corpus_hash": corpus_hash,
        "recommended_average_shot_length_sec": overall_asl,
        "live_premiere_sequence": live_seq if has_live else None,
        "reference_videos": videos_report,
        "reference_xml_timelines": xmls_report,
        "next_step": f"Synthesize these pacing and track metrics into {dna_file}",
    }

    raw_scan_file.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
