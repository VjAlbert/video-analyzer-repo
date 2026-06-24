# CHANGES

## Refactor: honesty, security, and correctness pass

### Security fix — `eval()` removed from `process_video.py`

`fps_original` was computed with `eval(video_stream.get("r_frame_rate", "0/1"))`,
passing a string from untrusted ffprobe metadata directly to Python's `eval()`.
Replaced with `_parse_rate()`, a safe fraction parser that splits on `/` and
catches `ValueError` / `ZeroDivisionError`. No `eval`, `exec`, `os.system`, or
`shell=True` remains anywhere in the codebase.

### Honesty fix — character detection reframed as visual scene clustering

`detect_characters.py` claimed to "detect characters" using HSV histogram
clustering. HSV histograms measure color/composition similarity, not identity —
they cannot distinguish two people wearing the same color outfit, or tell apart
AI-generated characters with similar palettes.

Changes:
- Renamed `detect_characters.py` → `cluster_frames.py`
- JSON key `character_count_detected` → `visual_cluster_count`
- Output key `characters` (list) → `clusters`; `character_id` → `cluster_id`
- User-facing language changed from "character detection" to
  "visual scene clustering — groups frames by color/composition similarity
  to help pick representative frames"
- Script is now explicitly optional in the pipeline
- **Character identification is now performed by Claude Vision** (SKILL.md
  Step 4): inspect 5–8 representative frames, count and describe distinct
  characters. The count and identity come from visual judgment, not histograms.
- README updated to reflect accurate capability language throughout

### Cost transparency — frames capped at 1568 px, token estimates added

The ffmpeg scale filter was already present but capped at 1280 px. Updated to
1568 px (Claude Vision's billing boundary for ~1,400 tokens/frame).

Filter changed from:
```
scale='min(1280,iw):-2'
```
to:
```
scale='min(1568,iw)':'min(1568,ih)':force_original_aspect_ratio=decrease
```

SKILL.md now states:
- Character-counting pass (5–8 frames): ~8–12k vision tokens
- Full timeline (up to 30 frames): ~40k+ vision tokens

### Path and naming consistency

- All SKILL.md script references updated to `cluster_frames.py`
- `build_json_report.py` updated to read `clusters.json` and use
  `visual_cluster_count`; character list is now built from `--character-names`
  (Claude Vision output), with clustering data as a fallback
- Dead `releases/` download link replaced with accurate path to
  `video-analyzer/dist/video-analyzer.skill`
- `--similarity-threshold` now documented consistently in both README and SKILL.md

### README rewrite

Full rewrite: accurate capability claims, honest Limitations section
(vision-model judgment, heuristic clustering, no speaker diarization),
correct script paths, zero-setup selling point preserved and explained.
