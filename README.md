# video-analyzer — Claude Skill

> **Converts any video file into a comprehensive AI-readable report (Markdown + JSON)**
> — because Claude Projects don't accept `.mp4` uploads.

A [Claude skill](https://github.com/anthropics/skills) that extracts everything
meaningful from a video:

- **Audio transcript** with timestamps (Whisper, multilingual, no API key needed)
- **Visual frame analysis** — character identification and scene description by Claude Vision
- **Visual scene clustering** — groups frames by color/composition to aid frame selection (heuristic, not face recognition)
- **Dual output**: human-readable `.md` + machine-readable `.json`

No HuggingFace token, no gated models, no cloud inference for vision or audio — everything
runs locally except the Claude Vision calls that Claude Code already makes.

---

## What the skill actually does

| Step | What happens | Technology |
|------|-------------|------------|
| Frame extraction | Pulls one frame every ~2 s (configurable), capped at 30 frames, resized to ≤1568 px long edge | ffmpeg |
| Audio transcription | Transcribes the audio track with timestamps | openai-whisper (local) |
| Scene clustering | Groups frames by HSV histogram similarity → picks representative frames | opencv (local heuristic) |
| Character identification | Inspects representative frames and counts/describes distinct characters | Claude Vision |
| Report assembly | Combines all data into Markdown + JSON | Python |

**Character identification is performed by Claude Vision**, not by a face detector or
ML classifier. The clustering step is a frame-selection aid — it groups frames by
visual similarity so Claude doesn't need to inspect all 30 frames for a quick
character count (~8–12k tokens vs ~40k+ for a full timeline).

---

## Sample output

Input: any `.mp4 / .mov / .avi / .mkv`
Output in ~60–120 s:

```
SC00_video_report.md      ← human-readable report
SC00_video_report.json    ← structured data for AI ingestion
```

JSON schema:

```json
{
  "schema_version": "1.0",
  "metadata": { "duration_formatted": "00:02:44", "width": 1080, "fps_original": 25.0, ... },
  "characters": {
    "count": 4,
    "count_source": "claude_vision",
    "list": [
      { "character_id": 1, "name": "Gioggia" },
      ...
    ]
  },
  "audio": {
    "has_audio": true,
    "transcript_segments": [
      { "timestamp": "00:00:00", "text": "Ragazzi, questo weekend..." },
      ...
    ]
  },
  "visual_timeline": [...],
  "summary": "...",
  "key_observations": [...]
}
```

---

## Requirements

Auto-installed on first run:

| Package | Purpose |
|---------|---------|
| `ffmpeg` | Frame extraction, audio extraction (must be on PATH) |
| `openai-whisper` | Local audio transcription |
| `opencv-python-headless` | HSV histogram clustering for frame selection |
| `numpy` | Array math for clustering |
| `Pillow` | Image utilities |

None of these require a HuggingFace token or network model download beyond the
first Whisper model pull (~74 MB for `base`).

---

## Installation

### In Claude Code

```bash
/plugin install video-analyzer@<your-github-username>
```

### Manual (Claude.ai)

1. Download `video-analyzer/dist/video-analyzer.skill` from this repository
2. Go to **Claude.ai → Settings → Skills → Upload skill**

---

## Usage

Once installed, upload a video and write:

> *"analizza questo video"*
> *"crea un report da questo mp4"*
> *"what's in this video?"*
> *"transcribe and summarize this clip"*

The skill triggers automatically on any video file mention.

---

## Parameters

| Flag | Default | Description |
|------|---------|-------------|
| `--fps` | 0.5 | Frames/sec to extract (1 frame every 2 s) |
| `--max-frames` | 30 | Max frames extracted |
| `--model` | base | Whisper model: `tiny` / `base` / `small` / `medium` |
| `--similarity-threshold` | 0.72 | Scene clustering sensitivity (0–1); higher = stricter grouping |

---

## Scripts

| Script | Purpose |
|--------|---------|
| `video-analyzer/scripts/process_video.py` | Extract frames (≤1568 px), audio, metadata via ffmpeg + Whisper |
| `video-analyzer/scripts/cluster_frames.py` | Group frames by HSV histogram similarity → pick representative frames |
| `video-analyzer/scripts/build_json_report.py` | Assemble final JSON from all extracted data + Claude Vision output |

---

## Limitations

- **Character identification is a vision-model judgment.** Claude Vision may miss
  non-speaking background figures, merge lookalikes with similar clothing, or
  miscount characters in crowded or fast-cut scenes. The result is an estimate,
  not a ground-truth count.

- **Scene clustering is a heuristic.** HSV histogram similarity groups frames by
  dominant color and composition, not by semantic content. It is useful for
  picking representative frames but does not detect faces, recognize individuals,
  or guarantee that each cluster corresponds to a distinct character.

- **No speaker diarization.** The transcript does not attribute speech to
  individual speakers. Speaker diarization was considered but rejected to preserve
  the zero-setup property (tools like `pyannote` require a HuggingFace token and
  add significant setup complexity).

- **Whisper accuracy varies.** The `base` model is fast but less accurate on
  accented speech, technical terminology, or low-quality audio. Use `--model small`
  or `--model medium` for better results at the cost of speed.

---

## License

MIT — see [LICENSE](LICENSE)

---

## Contributing

Issues and PRs welcome. If you improve character identification (e.g. add
configurable frame sampling strategies) or output formats, please open a PR.

To submit to the official Anthropic skills directory:

```bash
# Fork https://github.com/anthropics/skills
# Copy the video-analyzer/ folder into skills/
# Open a pull request
```
