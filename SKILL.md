---
name: premiere-editing-dna
description: >-
  Cross-platform (Windows & macOS) AI Agent Skill & MCP Server for Adobe
  Premiere Pro that extracts an editor's or brand's Editing DNA from previous
  approved edits (.prproj sequences, .xml timelines, or .mp4/.mov exports) and
  builds complete, editable, multi-track Premiere Pro sequences (V1 A-Roll with
  auto-silence cutting & punch-in zooms, V2 B-Roll, V3 Overlays, A1 Dialogue,
  A2 SFX, A3 Ducked Music Bed, Sequence Markers, and .srt Captions) from raw
  footage and a text brief.
---

# Premiere Editing DNA (`premiere-editing-dna`)

A cross-platform (**Windows and macOS**) AI Agent Skill & Zero-Dependency MCP Server for **Adobe Premiere Pro** that learns a creator's or company's **Editing DNA** from their previous approved edits and turns raw footage + a text brief into a **100% editable, multi-track Premiere Pro sequence** (`V1`–`V3` video tracks, `A1`–`A3` audio tracks, dynamic zoom cuts, audio ducking, sequence markers, and `.srt` captions).

---

## Cross-Platform Execution Notes (Windows & macOS)

- **Python Command:**
  - **Windows (PowerShell / CMD):** Use `python` (or `py -3`).
  - **macOS:** Use `python3`.
- **Skill Directory Resolution:**
  - Determine `<SKILL_DIR>` as `.agents/skills/premiere-editing-dna` (workspace) or `~/.gemini/config/skills/premiere-editing-dna` (global).
- **Dual-Bridge Architecture (`scripts/premiere_cli.py` + `scripts/build_premiere_sequence.py`):**
  1. **Auto-Installed CEP HTTP-to-ExtendScript Bridge (`127.0.0.1:8088`)**: Automatically enabled via `PlayerDebugMode = 1` and installed into Adobe's CEP extensions folder so Premiere Pro exposes live `app.project` inspection and file/sequence import.
  2. **Native FCP7 `xmeml v4` Sequence Compiler + OS Opener**: Compiles frame-accurate multi-track Premiere sequences (`.xml` + `.srt`) and opens them directly inside Premiere Pro even if the CEP panel hasn't been initialized yet.

---

## Stage 0: Zero-Touch Setup & Connection Check

On first run (or if `premiere_*` MCP tools are not yet loaded in the session), run:

```bash
python3 <SKILL_DIR>/scripts/setup_premiere_mcp.py
```

- Automatically locates Adobe Premiere Pro on Windows or macOS, sets `PlayerDebugMode = 1` for `CSXS.9`–`CSXS.12`, installs the bundled CEP extension (`com.vamshicreates.premieremcp`), and registers `"premiere-pro"` in `~/.gemini/config/mcp_config.json`.

---

## The 5-Stage Editing DNA $\rightarrow$ Brief/Footage $\rightarrow$ Premiere Timeline Pipeline

### Stage 1: Editing DNA Extraction & Caching (`.editing-dna/editing_dna.json`)

Whenever the user provides previous approved video edits (`.mp4`, `.mov`, `.xml` timelines, or an open sequence in Premiere Pro):

1. **Run the Automated Editing DNA Scanner**:
   ```bash
   python3 <SKILL_DIR>/scripts/extract_editing_dna.py <PATH_TO_PREVIOUS_EDITS> --state-dir .editing-dna
   ```
   - **If `status == "CACHE_HIT"`**: Read `.editing-dna/editing_dna.json` directly and proceed to Stage 2.
   - **If `status == "SCAN_COMPLETED"`**:
     - Extracts exact sequence resolution (`1080x1920` 9:16 vs `1920x1080` 16:9), frame rate (`23.976`, `29.97`, `30`, `60`), **Average Shot Length (`ASL`)**, **Hook Cut Pacing** (first 5 seconds), **Cuts Per Minute (`CPM`)**, silence pause thresholds, and track layout from active Premiere sequences or reference videos.
2. **Synthesize & Save `.editing-dna/editing_dna.json`**:
   ```json
   {
     "editor_or_brand": "Company / Creator Name",
     "corpus_hash": "<from_raw_editing_scan>",
     "sequence_defaults": {
       "width": 1080,
       "height": 1920,
       "aspect_ratio": "9:16",
       "fps": 30.0
     },
     "pacing_dna": {
       "hook_asl_sec": 1.6,
       "body_asl_sec": 2.8,
       "silence_threshold_db": -35.0,
       "min_silence_to_cut_sec": 0.28,
       "cut_padding_sec": 0.08,
       "punch_in_zoom_scale_pct": 112.0,
       "punch_in_cadence": "every_2nd_cut"
     },
     "track_architecture": {
       "V1": "Primary A-Roll (Tightened Dialogue + Alternating Punch-In Zooms)",
       "V2": "B-Roll Cutaways & Product Demos",
       "V3": "Graphics, Callouts & Title Overlays",
       "A1": "Primary Dialogue (0 dB normalized)",
       "A2": "SFX Whooshes, Hits & Risers (-9 dB)",
       "A3": "Background Music Bed (-20 dB ducked under dialogue)"
     }
   }
   ```

---

### Stage 2: Raw Footage Silence-Cutting & Beat Mapping

When the user provides raw footage (A-roll, B-roll, SFX, BGM) and a **text brief**:

1. **Auto-Cut Silence & Dead Air on Raw A-Roll**:
   ```bash
   python3 <SKILL_DIR>/scripts/build_premiere_sequence.py auto-cut <RAW_AROLL_VIDEO> --noise-db -35 --min-silence 0.28 --zoom-scale 112
   ```
   - Returns the exact frame-accurate list of active speech segments (`v1_aroll`) with alternating `100%` / `112%` `Basic Motion` scale values matching the editor's DNA.
2. **Map the Brief onto Multi-Track Layers**:
   - Place tightened A-Roll segments on **`V1` / `A1`**.
   - Schedule B-Roll clips (`v2_broll`) on **`V2`** over visual transitions or key talking points without cutting `A1` dialogue.
   - Schedule Graphic Overlays / Title Cards (`v3_overlays`) on **`V3`**.
   - Place transition SFX (`a2_sfx`) on **`A2`** at major cut/B-roll entrances (`-9 dB`).
   - Place the Music Bed (`a3_bgm`) on **`A3`** ducked to `-20 dB`.
   - Add Sequence Markers (`markers`) and synchronized `.srt` caption cues (`captions`).

---

### Stage 3: Write `timeline_spec.json` & Compile the Premiere Pro Sequence

Write the declarative `timeline_spec.json`:

```json
{
  "sequence": {
    "name": "Brand_Edit_01",
    "width": 1080,
    "height": 1920,
    "fps": 30.0
  },
  "outputXml": "./output/Brand_Edit_01.xml",
  "outputSrt": "./output/Brand_Edit_01.srt",
  "v1_aroll": [
    { "name": "Hook_Cut_01", "path": "/abs/path/aroll.mp4", "inSec": 1.20, "outSec": 3.10, "scale": 100.0, "gainDb": 0.0 },
    { "name": "Hook_Cut_02_Zoom", "path": "/abs/path/aroll.mp4", "inSec": 3.65, "outSec": 6.10, "scale": 112.0, "gainDb": 0.0 }
  ],
  "v2_broll": [
    { "name": "Product_Demo_Broll", "path": "/abs/path/broll_01.mp4", "startSec": 1.90, "inSec": 0.50, "durationSec": 2.20, "scale": 100.0 }
  ],
  "v3_overlays": [
    { "name": "Title_Card_PNG", "path": "/abs/path/callout.png", "startSec": 0.0, "durationSec": 1.80, "scale": 100.0 }
  ],
  "a2_sfx": [
    { "name": "Whoosh_Transition", "path": "/abs/path/whoosh.wav", "startSec": 1.85, "durationSec": 0.80, "gainDb": -9.0 }
  ],
  "a3_bgm": [
    { "name": "Brand_BGM_Bed", "path": "/abs/path/bgm.mp3", "startSec": 0.0, "inSec": 0.0, "gainDb": -20.0 }
  ],
  "markers": [
    { "name": "HOOK", "timeSec": 0.0, "comment": "High-retention opening cut" },
    { "name": "B-ROLL ENTRANCE", "timeSec": 1.90, "comment": "Visual proof overlay" }
  ],
  "captions": [
    { "startSec": 0.0, "endSec": 1.90, "text": "Stop wasting hours cutting silence by hand." },
    { "startSec": 1.90, "endSec": 4.35, "text": "Our Editing DNA builds the entire timeline automatically." }
  ]
}
```

Compile and open/import directly into Adobe Premiere Pro:

```bash
python3 <SKILL_DIR>/scripts/build_premiere_sequence.py build ./output/timeline_spec.json --open
```

---

### Stage 4: Timeline Verification & Live Refinement

1. Verify that `build_premiere_sequence.py` outputs `"status": "success"` with zero missing file paths.
2. If the live CEP bridge (`127.0.0.1:8088`) is active, call `premiere_cli.py inspect-sequence` (or `premiere_inspect_sequence`) to verify the imported sequence's track count, total runtime, and Average Shot Length against `.editing-dna/editing_dna.json`.
3. Deliver the open Premiere Pro timeline, the `.xml` sequence file, and the synchronized `.srt` caption file to the user.

---

## Embedded Laya Decision Gate (`NandhaKishorM/laya`) — Call Laya ONLY When Necessary

This skill embeds the **[Laya Non-Autoregressive Decision Model (`https://github.com/NandhaKishorM/laya`)](https://github.com/NandhaKishorM/laya)** inside [`scripts/laya_decision_gate.py`](scripts/laya_decision_gate.py) (`from laya import Router`).

### Strict Execution Policy: When to Call Laya vs. Manual Execution

1. **BASIC / EXPLICIT TASKS → DO NOT CALL LAYA (Execute Directly & Manually)**:
   - If the user gives a clear, direct, or single-step command (for example: *"add a marker at 12.5 seconds"*, *"cut silence shorter than 0.4s"*, *"place clip on V1 at 0s"*, *"set audio ducking to -18dB"*), **DO NOT call Laya**.
   - Execute the step directly using the skill's native CLI/MCP tools to keep execution instant and zero-overhead.
2. **COMPLEX / AMBIGUOUS MULTI-BRANCH TASKS → CALL LAYA (`laya_decision_gate.py`)**:
   - Call Laya **only when** a genuine typed decision (`choice`, `score`, `noul`) across multiple creative lanes or ambiguous requirements is needed (for example: *Triage a multi-topic transcript into Hook, Core Story, and Cut segments with pacing & B-roll strategy*; *Choose the optimal narrative rhythm and transition density for an ambiguous multi-clip brief*).
   - Run the Laya Decision Gate:
     ```bash
     python3 scripts/laya_decision_gate.py --state "<user_brief_or_complex_state>"
     ```
   - `laya_decision_gate.py` automatically runs `should_call_laya()` first:
     - If the task is basic, it immediately returns `"laya_called": false, "execution_mode": "direct_manual_execution"` without loading neural weights.
     - If the task is genuinely complex, it invokes `laya.Router().predict(...)` in a single forward pass (~33ms) with calibrated confidence gating (`min_confidence=0.55`) and neutral `noul` labels (`{"true": "A", "false": "B"}`).
   - To install the `laya` neural weights package (`pip install laya`) on a machine:
     ```bash
     python3 scripts/laya_decision_gate.py --install
     ```
