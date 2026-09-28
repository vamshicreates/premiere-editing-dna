#!/usr/bin/env python3
"""
Multi-Track Premiere Pro Live Foreground Builder & XML/SRT Compiler (`scripts/build_premiere_sequence.py`).

How it works so the user watches the edit happen live inside Premiere Pro (macOS & Windows):
1. Brings Adobe Premiere Pro to the foreground (`bring_premiere_to_front`).
2. When the live CEP Bridge (`127.0.0.1:8088`) is online, executes **Live Step-by-Step Timeline Assembly**:
   - Creates organized Project Bins (`01_A_Roll`, `02_B_Roll`, `03_Audio_SFX_BGM`, `04_Graphics`)
   - Places each `V1`/`A1` cut one-by-one onto the active sequence, moving the playhead to each cut
     and applying `Motion -> Scale` (`112%` punch-in zoom) in real time so the user sees every cut
     and zoom happen live in the Timeline and Program Monitor!
   - Places `V2` B-Roll, `V3` Overlays, `A2` SFX, `A3` Ducked Music Bed, and Sequence Markers step-by-step!
3. Also writes the complete FCP7 `xmeml version="4"` `.xml` sequence and `.srt` captions to disk
   (and imports them automatically if the CEP bridge wasn't open yet).
"""

import argparse
import json
import math
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.parse
import xml.etree.ElementTree as ET
from pathlib import Path
from xml.dom import minidom

SCRIPTS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS_DIR))

from premiere_cli import bring_premiere_to_front, call_cep_bridge, cmd_import_into_premiere  # noqa: E402


def path_to_premiere_url(file_path: str) -> str:
    """Convert a local Windows or macOS path to Premiere-compatible `file://localhost/...` URI."""
    p = Path(file_path).resolve()
    posix = p.as_posix()
    if not posix.startswith("/"):
        posix = "/" + posix
    encoded = urllib.parse.quote(posix, safe="/:")
    return f"file://localhost{encoded}"


def probe_media_duration(file_path: str) -> float:
    ffprobe = shutil.which("ffprobe") or "/opt/homebrew/bin/ffprobe" or "/usr/local/bin/ffprobe"
    if os.path.exists(ffprobe) or shutil.which("ffprobe"):
        try:
            cmd = [
                shutil.which("ffprobe") or ffprobe,
                "-v", "error",
                "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1",
                str(file_path),
            ]
            return round(float(subprocess.check_output(cmd, text=True, timeout=15).strip()), 3)
        except Exception:
            pass
    return 60.0


def detect_speech_segments(
    video_path: str,
    noise_db: float = -35.0,
    min_silence_sec: float = 0.30,
    pad_sec: float = 0.08,
    zoom_scale: float = 112.0,
) -> list[dict]:
    """Run ffmpeg silencedetect on raw A-roll and return active speech segments."""
    total_dur = probe_media_duration(video_path)
    ffmpeg = shutil.which("ffmpeg") or "/opt/homebrew/bin/ffmpeg" or "/usr/local/bin/ffmpeg"
    if not (os.path.exists(ffmpeg) or shutil.which("ffmpeg")):
        return [{"path": str(Path(video_path).resolve()), "inSec": 0.0, "outSec": total_dur, "scale": 100.0}]

    cmd = [
        shutil.which("ffmpeg") or ffmpeg,
        "-hide_banner",
        "-i", str(video_path),
        "-af", f"silencedetect=noise={noise_db}dB:d={min_silence_sec}",
        "-f", "null",
        "-",
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    stderr = proc.stderr or ""

    starts = [float(m.group(1)) for m in re.finditer(r"silence_start:\s*([0-9.]+)", stderr)]
    ends = [float(m.group(1)) for m in re.finditer(r"silence_end:\s*([0-9.]+)", stderr)]

    silences = []
    for i, st in enumerate(starts):
        en = ends[i] if i < len(ends) else total_dur
        silences.append((st, en))

    speech = []
    cursor = 0.0
    abs_path = str(Path(video_path).resolve())
    cut_idx = 0

    for st, en in silences:
        seg_in = max(0.0, cursor - (pad_sec if cursor > 0 else 0.0))
        seg_out = min(total_dur, st + pad_sec)
        if seg_out - seg_in >= 0.35:
            scale = zoom_scale if (cut_idx % 2 == 1) else 100.0
            speech.append({
                "name": f"{Path(video_path).stem}_cut_{cut_idx + 1:02d}",
                "path": abs_path,
                "inSec": round(seg_in, 3),
                "outSec": round(seg_out, 3),
                "scale": scale,
                "gainDb": 0.0,
            })
            cut_idx += 1
        cursor = en

    if total_dur - cursor >= 0.35:
        speech.append({
            "name": f"{Path(video_path).stem}_cut_{cut_idx + 1:02d}",
            "path": abs_path,
            "inSec": round(max(0.0, cursor - pad_sec), 3),
            "outSec": round(total_dur, 3),
            "scale": zoom_scale if (cut_idx % 2 == 1) else 100.0,
            "gainDb": 0.0,
        })

    if not speech:
        speech.append({"name": Path(video_path).stem, "path": abs_path, "inSec": 0.0, "outSec": total_dur, "scale": 100.0})

    return speech


def execute_live_step_by_step_in_premiere(spec: dict, step_delay_sec: float = 0.20) -> dict | None:
    """
    If the live CEP bridge (`127.0.0.1:8088`) is online, build the sequence
    clip-by-clip and track-by-track in the foreground so the user watches every cut,
    zoom, B-roll placement, audio ducking, and marker happen live on screen!
    """
    bring_premiere_to_front(auto_open_bridge_menu=True)
    ping = call_cep_bridge("/ping", "GET", timeout=2.5)
    if not ping or ping.get("status") != "success":
        return None

    seq_cfg = spec.get("sequence", {})
    seq_name = seq_cfg.get("name", "Live_AI_Edit")
    width = int(seq_cfg.get("width", 1080))
    height = int(seq_cfg.get("height", 1920))

    live_steps_executed = []
    cursor_sec = 0.0

    # 1. Place V1 + A1 A-Roll Cuts step-by-step
    for idx, item in enumerate(spec.get("v1_aroll", [])):
        in_sec = float(item.get("inSec", 0.0))
        out_sec = float(item.get("outSec", in_sec + 3.0))
        dur_sec = max(0.1, out_sec - in_sec)
        start_sec = float(item["startSec"]) if "startSec" in item else cursor_sec
        cursor_sec = max(cursor_sec, round(start_sec + dur_sec, 3))

        res = call_cep_bridge(
            "/place-clip",
            "POST",
            {
                "sequenceName": seq_name,
                "width": width,
                "height": height,
                "binName": "01_A_Roll",
                "trackType": "video",
                "trackIndex": 0,
                "name": item.get("name") or f"A_Roll_{idx+1}",
                "path": str(Path(item["path"]).resolve()),
                "inSec": in_sec,
                "outSec": out_sec,
                "startSec": start_sec,
                "scale": float(item.get("scale", 100.0)),
                "gainDb": float(item.get("gainDb", 0.0)),
            },
            timeout=25.0,
        )
        live_steps_executed.append({"step": f"V1_Cut_{idx+1}", "response": res})
        time.sleep(step_delay_sec)

    # 2. Place V2 B-Roll Cutaways step-by-step
    for idx, item in enumerate(spec.get("v2_broll", [])):
        in_sec = float(item.get("inSec", 0.0))
        dur_sec = float(item.get("durationSec") or (float(item.get("outSec", 2.5)) - in_sec))
        out_sec = in_sec + dur_sec
        start_sec = float(item.get("startSec", 0.0))

        res = call_cep_bridge(
            "/place-clip",
            "POST",
            {
                "binName": "02_B_Roll",
                "trackType": "video",
                "trackIndex": 1,
                "name": item.get("name") or f"B_Roll_{idx+1}",
                "path": str(Path(item["path"]).resolve()),
                "inSec": in_sec,
                "outSec": out_sec,
                "startSec": start_sec,
                "scale": float(item.get("scale", 100.0)),
            },
            timeout=25.0,
        )
        live_steps_executed.append({"step": f"V2_BRoll_{idx+1}", "response": res})
        time.sleep(step_delay_sec)

    # 3. Place V3 Overlays / Graphics step-by-step
    for idx, item in enumerate(spec.get("v3_overlays", [])):
        dur_sec = float(item.get("durationSec", 3.0))
        start_sec = float(item.get("startSec", 0.0))
        res = call_cep_bridge(
            "/place-clip",
            "POST",
            {
                "binName": "04_Graphics",
                "trackType": "video",
                "trackIndex": 2,
                "name": item.get("name") or f"Overlay_{idx+1}",
                "path": str(Path(item["path"]).resolve()),
                "inSec": 0.0,
                "outSec": dur_sec,
                "startSec": start_sec,
                "scale": float(item.get("scale", 100.0)),
            },
            timeout=25.0,
        )
        live_steps_executed.append({"step": f"V3_Overlay_{idx+1}", "response": res})
        time.sleep(step_delay_sec)

    # 4. Place A2 SFX step-by-step
    for idx, item in enumerate(spec.get("a2_sfx", [])):
        dur_sec = float(item.get("durationSec", 1.2))
        start_sec = float(item.get("startSec", 0.0))
        res = call_cep_bridge(
            "/place-clip",
            "POST",
            {
                "binName": "03_Audio_SFX_BGM",
                "trackType": "audio",
                "trackIndex": 1,
                "name": item.get("name") or f"SFX_{idx+1}",
                "path": str(Path(item["path"]).resolve()),
                "inSec": 0.0,
                "outSec": dur_sec,
                "startSec": start_sec,
                "gainDb": float(item.get("gainDb", -9.0)),
            },
            timeout=25.0,
        )
        live_steps_executed.append({"step": f"A2_SFX_{idx+1}", "response": res})
        time.sleep(step_delay_sec)

    # 5. Place A3 Ducked Music Bed
    for idx, item in enumerate(spec.get("a3_bgm", [])):
        start_sec = float(item.get("startSec", 0.0))
        in_sec = float(item.get("inSec", 0.0))
        end_sec = float(item.get("endSec", max(cursor_sec, 15.0)))
        out_sec = in_sec + max(1.0, end_sec - start_sec)
        res = call_cep_bridge(
            "/place-clip",
            "POST",
            {
                "binName": "03_Audio_SFX_BGM",
                "trackType": "audio",
                "trackIndex": 2,
                "name": item.get("name") or f"BGM_{idx+1}",
                "path": str(Path(item["path"]).resolve()),
                "inSec": in_sec,
                "outSec": out_sec,
                "startSec": start_sec,
                "gainDb": float(item.get("gainDb", -20.0)),
            },
            timeout=25.0,
        )
        live_steps_executed.append({"step": f"A3_BGM_{idx+1}", "response": res})
        time.sleep(step_delay_sec)

    # 6. Add Sequence Markers step-by-step
    for idx, m in enumerate(spec.get("markers", [])):
        res = call_cep_bridge(
            "/add-marker",
            "POST",
            {
                "name": m.get("name", f"Marker_{idx+1}"),
                "comment": m.get("comment", ""),
                "timeSec": float(m.get("timeSec", 0.0)),
                "colorIndex": idx % 6,
            },
            timeout=10.0,
        )
        live_steps_executed.append({"step": f"Marker_{idx+1}", "response": res})
        time.sleep(0.12)

    # Return playhead to 00:00:00:00 ready for playback
    call_cep_bridge("/set-playhead", "POST", {"timeSec": 0.0}, timeout=5.0)
    return {
        "mode": "live_foreground_step_by_step",
        "stepsExecuted": len(live_steps_executed),
        "details": live_steps_executed,
    }


def add_rate_node(parent: ET.Element, timebase: int, ntsc: bool = False):
    rate = ET.SubElement(parent, "rate")
    ET.SubElement(rate, "timebase").text = str(timebase)
    ET.SubElement(rate, "ntsc").text = "TRUE" if ntsc else "FALSE"


def add_scale_filter(clipitem: ET.Element, scale_pct: float):
    if abs(scale_pct - 100.0) < 0.1:
        return
    filt = ET.SubElement(clipitem, "filter")
    eff = ET.SubElement(filt, "effect")
    ET.SubElement(eff, "name").text = "Basic Motion"
    ET.SubElement(eff, "effectid").text = "basic"
    ET.SubElement(eff, "effectcategory").text = "motion"
    ET.SubElement(eff, "effecttype").text = "motion"
    ET.SubElement(eff, "mediatype").text = "video"
    param = ET.SubElement(eff, "parameter")
    ET.SubElement(param, "parameterid").text = "scale"
    ET.SubElement(param, "name").text = "Scale"
    ET.SubElement(param, "valuemin").text = "0"
    ET.SubElement(param, "valuemax").text = "1000"
    ET.SubElement(param, "value").text = str(scale_pct)


def add_audio_gain_filter(clipitem: ET.Element, gain_db: float):
    if abs(gain_db) < 0.1:
        return
    linear_level = round(math.pow(10.0, gain_db / 20.0), 4)
    filt = ET.SubElement(clipitem, "filter")
    eff = ET.SubElement(filt, "effect")
    ET.SubElement(eff, "name").text = "Audio Levels"
    ET.SubElement(eff, "effectid").text = "audiolevels"
    ET.SubElement(eff, "effecttype").text = "audiolevels"
    ET.SubElement(eff, "mediatype").text = "audio"
    param = ET.SubElement(eff, "parameter")
    ET.SubElement(param, "parameterid").text = "level"
    ET.SubElement(param, "name").text = "Level"
    ET.SubElement(param, "valuemin").text = "0"
    ET.SubElement(param, "valuemax").text = "3.98107"
    ET.SubElement(param, "value").text = str(linear_level)


def format_srt_time(seconds: float) -> str:
    ms = int(round((seconds - int(seconds)) * 1000))
    total_sec = int(seconds)
    s = total_sec % 60
    m = (total_sec // 60) % 60
    h = total_sec // 3600
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def write_srt_captions(captions: list[dict], srt_path: Path) -> str:
    lines = []
    for idx, cap in enumerate(captions, start=1):
        st = format_srt_time(float(cap.get("startSec", 0.0)))
        en = format_srt_time(float(cap.get("endSec", 2.0)))
        text = str(cap.get("text", "")).strip()
        lines.append(f"{idx}\n{st} --> {en}\n{text}\n")
    srt_path.parent.mkdir(parents=True, exist_ok=True)
    srt_path.write_text("\n".join(lines), encoding="utf-8")
    return str(srt_path)


def build_sequence_xml(spec: dict) -> dict:
    seq_cfg = spec.get("sequence", {})
    seq_name = seq_cfg.get("name", "AI_Edit_Sequence")
    width = int(seq_cfg.get("width", 1080))
    height = int(seq_cfg.get("height", 1920))
    fps = float(seq_cfg.get("fps", 30.0))
    timebase = int(round(fps))
    ntsc = abs(fps - round(fps)) > 0.001

    def sec_to_frames(sec: float) -> int:
        return int(round(float(sec) * timebase))

    xmeml = ET.Element("xmeml", version="4")
    sequence = ET.SubElement(xmeml, "sequence", id="sequence-1")
    ET.SubElement(sequence, "name").text = seq_name
    add_rate_node(sequence, timebase, ntsc)

    media = ET.SubElement(sequence, "media")
    video = ET.SubElement(media, "video")
    fmt = ET.SubElement(video, "format")
    sc = ET.SubElement(fmt, "samplecharacteristics")
    add_rate_node(sc, timebase, ntsc)
    ET.SubElement(sc, "width").text = str(width)
    ET.SubElement(sc, "height").text = str(height)
    ET.SubElement(sc, "anamorphic").text = "FALSE"
    ET.SubElement(sc, "pixelaspectratio").text = "square"
    ET.SubElement(sc, "fielddominance").text = "none"

    audio = ET.SubElement(media, "audio")
    ET.SubElement(audio, "numOutputChannels").text = "2"
    afmt = ET.SubElement(audio, "format")
    asc = ET.SubElement(afmt, "samplecharacteristics")
    ET.SubElement(asc, "depth").text = "16"
    ET.SubElement(asc, "samplerate").text = "48000"

    file_registry = {}
    clip_counter = 0

    def attach_file_node(clip_el: ET.Element, media_path: str, total_frames: int, has_audio: bool = True):
        abs_p = str(Path(media_path).resolve())
        if abs_p not in file_registry:
            fid = f"file-{len(file_registry) + 1}"
            file_registry[abs_p] = fid
            fnode = ET.SubElement(clip_el, "file", id=fid)
            ET.SubElement(fnode, "name").text = Path(abs_p).name
            ET.SubElement(fnode, "pathurl").text = path_to_premiere_url(abs_p)
            add_rate_node(fnode, timebase, ntsc)
            ET.SubElement(fnode, "duration").text = str(max(total_frames, 3600))
            fmed = ET.SubElement(fnode, "media")
            ET.SubElement(fmed, "video")
            if has_audio:
                faud = ET.SubElement(fmed, "audio")
                ET.SubElement(faud, "channelcount").text = "2"
        else:
            ET.SubElement(clip_el, "file", id=file_registry[abs_p])

    v1_track = ET.SubElement(video, "track")
    a1_track = ET.SubElement(audio, "track")
    timeline_cursor_frames = 0

    for item in spec.get("v1_aroll", []):
        clip_counter += 1
        in_f = sec_to_frames(item.get("inSec", 0.0))
        out_f = sec_to_frames(item.get("outSec", 3.0))
        dur_f = max(1, out_f - in_f)
        start_f = sec_to_frames(item["startSec"]) if "startSec" in item else timeline_cursor_frames
        end_f = start_f + dur_f
        timeline_cursor_frames = max(timeline_cursor_frames, end_f)

        cname = item.get("name") or Path(item["path"]).stem
        v_ci = ET.SubElement(v1_track, "clipitem", id=f"clipitem-v1-{clip_counter}")
        ET.SubElement(v_ci, "name").text = cname
        ET.SubElement(v_ci, "enabled").text = "TRUE"
        ET.SubElement(v_ci, "duration").text = str(out_f + 300)
        add_rate_node(v_ci, timebase, ntsc)
        ET.SubElement(v_ci, "start").text = str(start_f)
        ET.SubElement(v_ci, "end").text = str(end_f)
        ET.SubElement(v_ci, "in").text = str(in_f)
        ET.SubElement(v_ci, "out").text = str(out_f)
        attach_file_node(v_ci, item["path"], out_f + 300, has_audio=True)
        add_scale_filter(v_ci, float(item.get("scale", 100.0)))

        if item.get("includeAudio", True):
            a_ci = ET.SubElement(a1_track, "clipitem", id=f"clipitem-a1-{clip_counter}")
            ET.SubElement(a_ci, "name").text = cname
            ET.SubElement(a_ci, "enabled").text = "TRUE"
            ET.SubElement(a_ci, "duration").text = str(out_f + 300)
            add_rate_node(a_ci, timebase, ntsc)
            ET.SubElement(a_ci, "start").text = str(start_f)
            ET.SubElement(a_ci, "end").text = str(end_f)
            ET.SubElement(a_ci, "in").text = str(in_f)
            ET.SubElement(a_ci, "out").text = str(out_f)
            attach_file_node(a_ci, item["path"], out_f + 300, has_audio=True)
            add_audio_gain_filter(a_ci, float(item.get("gainDb", 0.0)))

    v2_track = ET.SubElement(video, "track")
    for item in spec.get("v2_broll", []):
        clip_counter += 1
        start_f = sec_to_frames(item.get("startSec", 0.0))
        in_f = sec_to_frames(item.get("inSec", 0.0))
        dur_sec = item.get("durationSec") or (float(item.get("outSec", 2.5)) - float(item.get("inSec", 0.0)))
        dur_f = max(1, sec_to_frames(dur_sec))
        out_f = in_f + dur_f
        end_f = start_f + dur_f
        timeline_cursor_frames = max(timeline_cursor_frames, end_f)

        v_ci = ET.SubElement(v2_track, "clipitem", id=f"clipitem-v2-{clip_counter}")
        ET.SubElement(v_ci, "name").text = item.get("name") or Path(item["path"]).stem
        ET.SubElement(v_ci, "enabled").text = "TRUE"
        ET.SubElement(v_ci, "duration").text = str(out_f + 300)
        add_rate_node(v_ci, timebase, ntsc)
        ET.SubElement(v_ci, "start").text = str(start_f)
        ET.SubElement(v_ci, "end").text = str(end_f)
        ET.SubElement(v_ci, "in").text = str(in_f)
        ET.SubElement(v_ci, "out").text = str(out_f)
        attach_file_node(v_ci, item["path"], out_f + 300, has_audio=False)
        add_scale_filter(v_ci, float(item.get("scale", 100.0)))

    v3_track = ET.SubElement(video, "track")
    for item in spec.get("v3_overlays", []):
        clip_counter += 1
        start_f = sec_to_frames(item.get("startSec", 0.0))
        dur_f = max(1, sec_to_frames(item.get("durationSec", 3.0)))
        end_f = start_f + dur_f

        v_ci = ET.SubElement(v3_track, "clipitem", id=f"clipitem-v3-{clip_counter}")
        ET.SubElement(v_ci, "name").text = item.get("name") or Path(item["path"]).stem
        ET.SubElement(v_ci, "enabled").text = "TRUE"
        ET.SubElement(v_ci, "duration").text = str(dur_f + 300)
        add_rate_node(v_ci, timebase, ntsc)
        ET.SubElement(v_ci, "start").text = str(start_f)
        ET.SubElement(v_ci, "end").text = str(end_f)
        ET.SubElement(v_ci, "in").text = "0"
        ET.SubElement(v_ci, "out").text = str(dur_f)
        attach_file_node(v_ci, item["path"], dur_f + 300, has_audio=False)
        add_scale_filter(v_ci, float(item.get("scale", 100.0)))

    a2_track = ET.SubElement(audio, "track")
    for item in spec.get("a2_sfx", []):
        clip_counter += 1
        start_f = sec_to_frames(item.get("startSec", 0.0))
        dur_f = max(1, sec_to_frames(item.get("durationSec", 1.2)))
        end_f = start_f + dur_f

        a_ci = ET.SubElement(a2_track, "clipitem", id=f"clipitem-a2-{clip_counter}")
        ET.SubElement(a_ci, "name").text = item.get("name") or Path(item["path"]).stem
        ET.SubElement(a_ci, "enabled").text = "TRUE"
        ET.SubElement(a_ci, "duration").text = str(dur_f + 100)
        add_rate_node(a_ci, timebase, ntsc)
        ET.SubElement(a_ci, "start").text = str(start_f)
        ET.SubElement(a_ci, "end").text = str(end_f)
        ET.SubElement(a_ci, "in").text = "0"
        ET.SubElement(a_ci, "out").text = str(dur_f)
        attach_file_node(a_ci, item["path"], dur_f + 100, has_audio=True)
        add_audio_gain_filter(a_ci, float(item.get("gainDb", -9.0)))

    a3_track = ET.SubElement(audio, "track")
    for item in spec.get("a3_bgm", []):
        clip_counter += 1
        start_f = sec_to_frames(item.get("startSec", 0.0))
        in_f = sec_to_frames(item.get("inSec", 0.0))
        end_f = sec_to_frames(item["endSec"]) if "endSec" in item else max(timeline_cursor_frames, sec_to_frames(15.0))
        dur_f = max(1, end_f - start_f)
        out_f = in_f + dur_f

        a_ci = ET.SubElement(a3_track, "clipitem", id=f"clipitem-a3-{clip_counter}")
        ET.SubElement(a_ci, "name").text = item.get("name") or Path(item["path"]).stem
        ET.SubElement(a_ci, "enabled").text = "TRUE"
        ET.SubElement(a_ci, "duration").text = str(out_f + 300)
        add_rate_node(a_ci, timebase, ntsc)
        ET.SubElement(a_ci, "start").text = str(start_f)
        ET.SubElement(a_ci, "end").text = str(end_f)
        ET.SubElement(a_ci, "in").text = str(in_f)
        ET.SubElement(a_ci, "out").text = str(out_f)
        attach_file_node(a_ci, item["path"], out_f + 300, has_audio=True)
        add_audio_gain_filter(a_ci, float(item.get("gainDb", -20.0)))

    ET.SubElement(sequence, "duration").text = str(max(timeline_cursor_frames, timebase))

    for m in spec.get("markers", []):
        m_el = ET.SubElement(sequence, "marker")
        ET.SubElement(m_el, "name").text = str(m.get("name", "Beat"))
        ET.SubElement(m_el, "comment").text = str(m.get("comment", ""))
        f_pos = sec_to_frames(m.get("timeSec", 0.0))
        ET.SubElement(m_el, "in").text = str(f_pos)
        ET.SubElement(m_el, "out").text = "-1"

    xml_bytes = ET.tostring(xmeml, encoding="utf-8")
    pretty_xml = minidom.parseString(xml_bytes).toprettyxml(indent="  ", encoding="utf-8").decode("utf-8")
    lines = pretty_xml.splitlines()
    if lines and lines[0].startswith("<?xml"):
        lines.insert(1, "<!DOCTYPE xmeml>")
    final_xml = "\n".join(lines)

    out_xml_path = Path(spec.get("outputXml", "./output/premiere_sequence.xml")).resolve()
    out_xml_path.parent.mkdir(parents=True, exist_ok=True)
    out_xml_path.write_text(final_xml, encoding="utf-8")

    out_srt_path = None
    if spec.get("captions"):
        srt_target = Path(spec.get("outputSrt", str(out_xml_path.with_suffix(".srt")))).resolve()
        out_srt_path = write_srt_captions(spec["captions"], srt_target)

    return {
        "status": "success",
        "sequenceName": seq_name,
        "durationSec": round(timeline_cursor_frames / max(1, timebase), 2),
        "outputXml": str(out_xml_path),
        "outputSrt": out_srt_path,
        "totalClips": clip_counter,
    }


def main():
    parser = argparse.ArgumentParser(description="Build multi-track Premiere Pro sequences live in the foreground")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_cut = sub.add_parser("auto-cut", help="Detect active speech cuts from a raw A-roll video via ffmpeg silencedetect")
    p_cut.add_argument("video", help="Path to raw A-roll video file")
    p_cut.add_argument("--noise-db", type=float, default=-35.0, help="Silence threshold in dB (default: -35)")
    p_cut.add_argument("--min-silence", type=float, default=0.30, help="Minimum silence duration to cut (default: 0.30s)")
    p_cut.add_argument("--zoom-scale", type=float, default=112.0, help="Alternating punch-in scale % (default: 112)")

    p_bld = sub.add_parser("build", help="Build a multi-track timeline live on screen in Premiere Pro (+ save XML & SRT)")
    p_bld.add_argument("spec_json", help="Path to timeline_spec.json")
    p_bld.add_argument("--open", action="store_true", help="Execute live in Premiere Pro (or auto-open XML if CEP panel is closed)")

    args = parser.parse_args()

    if args.cmd == "auto-cut":
        cuts = detect_speech_segments(
            args.video,
            noise_db=args.noise_db,
            min_silence_sec=args.min_silence,
            zoom_scale=args.zoom_scale,
        )
        print(json.dumps({"status": "success", "video": args.video, "cutCount": len(cuts), "v1_aroll": cuts}, indent=2))

    elif args.cmd == "build":
        spec = json.loads(Path(args.spec_json).read_text(encoding="utf-8"))
        res = build_sequence_xml(spec)
        if args.open:
            live_res = execute_live_step_by_step_in_premiere(spec)
            if live_res:
                res["live_execution"] = live_res
                if res.get("outputSrt"):
                    call_cep_bridge("/import", "POST", {"paths": [res["outputSrt"]]}, timeout=15.0)
            elif res.get("outputXml"):
                files_to_import = [res["outputXml"]]
                if res.get("outputSrt"):
                    files_to_import.append(res["outputSrt"])
                res["premiere_import"] = cmd_import_into_premiere(files_to_import)
        print(json.dumps(res, indent=2))


if __name__ == "__main__":
    main()
