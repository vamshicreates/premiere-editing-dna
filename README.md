# Premiere Editing DNA (`premiere-editing-dna`)

A cross-platform (**Windows and macOS**) AI Agent Skill & Zero-Dependency MCP Server for **Adobe Premiere Pro** that:
1. **Extracts your Editing DNA** from previous approved edits (active Premiere Pro sequences, `.xml` timelines, or exported `.mp4`/`.mov` reference videos) — capturing Average Shot Length (`ASL`), hook cut frequency, silence thresholds, punch-in zoom cadence, audio gain/ducking ratios, and track layout conventions.
2. **Turns raw footage + a text brief into a complete, multi-track, 100% editable Premiere Pro sequence** — complete with `V1` A-Roll (auto-cut silence + alternating `100%`/`112%` punch-in zooms), `V2` B-Roll cutaways, `V3` graphic overlays, `A1` dialogue, `A2` transition SFX, `A3` ducked music bed (`-20dB`), color-coded Sequence Markers, and a frame-accurate `.srt` subtitle file.

---

## ✨ Key Capabilities

1. **Zero-Touch Cross-Platform Setup (`scripts/setup_premiere_mcp.py`)**:
   - Automatically enables Adobe CEP `PlayerDebugMode = 1` across `CSXS.9`–`CSXS.12` on both Windows (`HKCU` registry — no admin required) and macOS (`defaults write`).
   - Auto-installs the bundled `com.vamshicreates.premieremcp` CEP extension (`assets/cep_extension`) which runs a local HTTP-to-ExtendScript bridge on `127.0.0.1:8088`.
   - Registers the zero-dependency `"premiere-pro"` Stdio MCP server in `~/.gemini/config/mcp_config.json`.

2. **Two-Pronged Editing DNA Extractor (`scripts/extract_editing_dna.py`)**:
   - **From Live Premiere Sequences or `.xml` Timelines**: Reads exact track layouts (`V1`–`V3`, `A1`–`A3`), clip counts, and Average Shot Length (`ASL`).
   - **From Reference Video Exports (`.mp4`, `.mov`)**: Uses `ffprobe` and `ffmpeg` scene-change detection (`select='gt(scene,0.26)'`) + `silencedetect` to measure exact Hook ASL (first 5s), Body ASL, Cuts Per Minute (`CPM`), and pause thresholds, caching everything in `.editing-dna/editing_dna.json`.

3. **Multi-Track Sequence & Caption Compiler (`scripts/build_premiere_sequence.py`)**:
   - Automatically strips dead air from raw A-roll via `ffmpeg silencedetect`.
   - Compiles a native Premiere Pro `xmeml version="4"` multi-track timeline with editable `Basic Motion` Scale filters, `Audio Levels` gain filters, Sequence Markers, and `.srt` captions, and imports/opens it directly inside Adobe Premiere Pro.

---

## 📂 Repository Structure

```text
premiere-editing-dna/
├── SKILL.md                            # Complete 5-Stage Agent Skill workflow
├── README.md                           # Quickstart & documentation
├── LICENSE                             # MIT License
├── assets/
│   └── cep_extension/                  # Auto-installed Premiere Pro CEP Bridge (127.0.0.1:8088)
│       ├── CSXS/manifest.xml
│       ├── index.html
│       └── host.jsx
└── scripts/
    ├── setup_premiere_mcp.py           # Cross-platform zero-touch installer (CEP + MCP config)
    ├── premiere_mcp_server.py          # Zero-dependency Stdio MCP server
    ├── premiere_cli.py                 # Unified CLI controller (CEP bridge + native XML opener)
    ├── extract_editing_dna.py          # Editing DNA analyzer (live sequence, XML, or MP4/MOV via ffmpeg)
    └── build_premiere_sequence.py      # Auto-silence cutter + multi-track Premiere XML & SRT compiler
```

---

## 🚀 Installation (Windows & macOS)

> **Prerequisite:** Adobe Premiere Pro installed on the laptop (plus `ffmpeg` on PATH for automatic silence/scene-cut analysis on raw `.mp4`/`.mov` files).

### Option 1: Zero-Touch via Antigravity Chat (Recommended)
Paste this single prompt into Antigravity:
> **"Install the skill from https://github.com/vamshicreates/premiere-editing-dna into `.agents/skills/premiere-editing-dna` and run its setup script."**

### Option 2: 1-Line Terminal Install
```bash
git clone https://github.com/vamshicreates/premiere-editing-dna.git .agents/skills/premiere-editing-dna && python3 .agents/skills/premiere-editing-dna/scripts/setup_premiere_mcp.py
```
*(On Windows PowerShell, replace `python3` with `python`).*

---

## 🎬 How to Use

1. **Extract Your Editing DNA (One-Time)**:
   Point Antigravity to a folder of your previous approved video edits (`.mp4`/`.mov` or `.xml`) or an open Premiere Pro sequence:
   > **"Extract our Editing DNA from `./approved-edits` and build a new multi-track Premiere Pro sequence from `./raw-footage` following this brief: [your brief]."**
2. **Generate Any Future Edit from Raw Footage + Brief**:
   Once `.editing-dna/editing_dna.json` is cached:
   > **"Using our Editing DNA, auto-cut `./raw-footage/aroll.mp4`, layer the B-roll and BGM, and open the full multi-track timeline in Premiere Pro."**
