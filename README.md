# 🎬 video-analyzer — Claude Skill

> **Converts any video file into a comprehensive AI-readable report (Markdown + JSON)**
> — because Claude Projects don't accept `.mp4` uploads.

A [Claude skill](https://github.com/anthropics/skills) that extracts everything meaningful from a video:
- 📝 **Audio transcript** with timestamps (Whisper, multilingual)
- 👁️ **Visual frame analysis** via Claude Vision
- 🧍 **Automatic character detection** (HSV-histogram clustering, no ML model needed)
- 📄 **Dual output**: structured `.md` + machine-readable `.json`

---

## Demo

Input: any `.mp4 / .mov / .avi / .mkv`  
Output in ~60–120 s:

```
SC00_video_report.md      ← human-readable report
SC00_video_report.json    ← structured data for AI ingestion
```

The JSON schema:
```json
{
  "schema_version": "1.0",
  "metadata": { "duration_formatted": "00:02:44", "width": 1080, ... },
  "characters": {
    "count": 4,
    "list": [
      { "character_id": 1, "name": "Gioggia", "appearances": 10, "first_seen": "00:00:38" },
      ...
    ]
  },
  "audio": {
    "has_audio": true,
    "language_detected": "Italian",
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

## Installation

### In Claude Code / Cowork

```bash
/plugin install video-analyzer@<your-github-username>
```

Or install the `.skill` file directly in Cowork → Settings → Skills → Upload.

### Manual (Claude.ai)

1. Download [`video-analyzer.skill`](releases)
2. Go to **Claude.ai → Settings → Skills → Upload skill**

---

## Requirements

Auto-installed on first run:
- `ffmpeg` (must be on PATH)
- `openai-whisper`
- `opencv-python-headless`
- `numpy`, `Pillow`

---

## Usage

Once installed, just upload a video and write:

> *"analizza questo video"*  
> *"crea un report da questo mp4"*  
> *"what's in this video?"*  
> *"transcribe and summarize this clip"*

The skill triggers automatically on any video file mention.

---

## Skill parameters

| Flag | Default | Description |
|------|---------|-------------|
| `--fps` | 0.5 | Frames/sec to extract (1 frame every 2 s) |
| `--max-frames` | 30 | Max frames extracted |
| `--model` | base | Whisper model: `tiny` / `base` / `small` / `medium` |
| `--similarity-threshold` | 0.72 | Character clustering sensitivity (0–1) |

---

## Scripts

| Script | Purpose |
|--------|---------|
| `process_video.py` | Extract frames, audio, metadata via ffmpeg + Whisper |
| `detect_characters.py` | Cluster frames by HSV histogram → character count |
| `build_json_report.py` | Assemble final JSON from all extracted data |

---

## Output format

See [`SKILL.md`](video-analyzer/SKILL.md) for the full Markdown report template.

---

## License

MIT — see [LICENSE](LICENSE)

---

## Contributing

Issues and PRs welcome. If you add support for a new output format or improve
character detection (e.g. face embeddings for live-action video), please open a PR.

To submit to the official Anthropic skills directory:
```bash
# Fork https://github.com/anthropics/skills
# Copy the video-analyzer/ folder into skills/
# Open a pull request
```
