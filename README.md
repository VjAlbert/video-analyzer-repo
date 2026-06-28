# video-analyzer

> Converts any video file into a comprehensive AI-readable report **(Markdown + JSON + PDF)**
> with RAG-ready timeline, Vision scene analysis, and semantic compression.

Originally built to work around the fact that Claude — and most current LLM interfaces —
cannot ingest video files directly. The pipeline solves this by decomposing any video into
primitives that any Vision-capable model can handle: extracted frames (JPEG), an audio
transcript (Whisper), and structured metadata (JSON).

As a result the skill is **model-agnostic**: it works with Claude, Gemini, GPT-4o, or any
other model that accepts images and text. The Vision model is a runtime parameter
(`--vision-model`), not a hard dependency. The default is `claude-haiku-4-5-20251001`;
substituting another model requires only changing that flag.

---

## Demo

Invoke the skill with any video path:

```
/video-analyzer "/path/to/video.mp4"
```

Three output files are produced automatically:

```
{nome}_report.md    ← human-readable narrative report
{nome}_report.json  ← RAG-ready structured data (schema v2.0)
{nome}_report.pdf   ← shareable visual report with thumbnails*
```

> \* PDF thumbnails are embedded when `ANTHROPIC_API_KEY` is set and Vision detects scene changes. Without the key, the PDF renders as text-only (~40 KB via reportlab).

---

## Installation

### Claude Code / Cowork (full execution)

```bash
/plugin install video-analyzer@VjAlbert
```

Or clone manually and register the skill:

```bash
git clone https://github.com/VjAlbert/video-analyzer-repo ~/video-analyzer
ln -sfn ~/video-analyzer ~/.claude/skills/video-analyzer   # Claude Code
```

Produces all three outputs: `.md` + `.json` + `.pdf`.

> ⚠️ **Note on large-v3-turbo**: the Whisper model is automatically downloaded on the first run (~1.6 GB). Make sure you have connection and disk space available before first use.

### Cowork Desktop

1. OPEN Cowork → Settings → Skills → Upload
2. Drag the folder `video-analyzer/` completa (non solo `SKILL.md`)
3. The skill will be available in the current session

### Claude.ai Desktop / Web (read-only mode)

Claude.ai does not support running Python or ffmpeg scripts. You can load `SKILL.md` as a custom instruction into a Claude Project for documentation and reference, but full execution requires Claude Code or Cowork.

---

## Requirements

```
Auto-installed on first run:
- ffmpeg                   (must be in your system PATH — check with: ffmpeg -version)
- openai-whisper           (default model: large-v3-turbo, ~1.6 GB on first download)
- opencv-python-headless
- numpy, Pillow
- reportlab                (PDF renderer — fallback if weasyprint is not available)
```

```bash
pip install openai-whisper opencv-python-headless numpy Pillow reportlab
```

> **Windows**: `weasyprint` requires GTK and is not native on Windows. The `reportlab` fallback is used automatically.

---

## Architecture v2.0

Three-stage pipeline with intermediate pivot format:

```
                  ┌─────────────────────────────┐
                  │         Input Video          │
                  └──────────────┬──────────────┘
                                 │
                     ┌───────────▼───────────┐
                     │   process_video.py    │
                     │  • ffprobe metadata   │
                     │  • adaptive sampling  │
                     │  • Whisper+confidence │
                     │  • Vision batch       │
                     └───────────┬───────────┘
                                 │
                     ┌───────────▼───────────┐
                     │  intermediate_nodes   │  ← pivot format
                     │      .json            │
                     └───────────┬───────────┘
                                 │
                  ┌──────────────▼──────────────┐
                  │   detect_characters.py      │  ← optional step
                  │  • Pass 1: Vision per frame │
                  │  • Pass 2: Python aggregation│
                  │  → character_appearances.json│
                  └──────────────┬──────────────┘
                                 │
               ┌─────────────────┴──────────────────┐
               │                                    │
   ┌───────────▼───────────┐          ┌─────────────▼────────────┐
   │   cluster_frames.py   │          │   build_json_report.py   │
   │  • HSV histogram      │          │   • text_clean           │
   │  • greedy clustering  │          │   • segment merging      │
   │  • representative     │          │   • keyword extraction   │
   │    frame selection    │          │   • global_index         │
   └───────────────────────┘          │   • visual_timeline      │
                                      │     bridge → nodes       │
                                      └─────────────┬────────────┘
                                                    │
                                       ┌────────────▼────────────┐
                                       │   build_pdf_report.py   │
                                       │  • thumbnail grid       │
                                       │  • weasyprint / rl      │
                                       └────────────┬────────────┘
                                                    │
                             ┌──────────────────────┼──────────────────────┐
                             ▼                      ▼                      ▼
                      *_report.md          *_report.json          *_report.pdf
```

**Pivot format** — `intermediate_nodes.json` decouples extraction from report generation. Each node maps one Whisper segment to its nearest visual scene change. `visual_delta` is populated by the Vision batch when `ANTHROPIC_API_KEY` is set; otherwise nodes carry `null` and the PDF renders without thumbnails.

---

## CLI Usage

### Step 1 — Pre-process the video

```bash
python scripts/process_video.py /path/to/video.mp4 \
    --output-dir /tmp/video_work \
    --model large-v3-turbo \
    --task transcribe
```

Frame sampling is automatic — no `--fps` flag needed. Pass `--fps 0.5` only to
force the legacy fixed-fps mode.

### Step 2 — Cluster frames (optional)

```bash
python scripts/cluster_frames.py \
    --frames-dir /tmp/video_work/frames \
    --output /tmp/video_work/clusters.json \
    --manifest /tmp/video_work/manifest.json \
    --similarity-threshold 0.72
```

### Step 2b — Track character appearances (optional)

```bash
python scripts/detect_characters.py \
    --work-dir /tmp/video_work \
    --character-names '{"1":"<Name> - <description>","2":"<Name> - <description>"}' \
    --vision-model claude-haiku-4-5-20251001 \
    --batch-size 10
```

Sends each extracted frame (batched) to the Vision model with the character catalog,
records which characters are visible per frame, and writes `character_appearances.json`
to `--work-dir`. `build_json_report.py` reads this file automatically if present.

Skip this step if character timeline tracking is not needed. Without it,
`first_seen` and `appearances` are reported as `"n/d"` in the JSON output.

### Step 3 — Compile the report

```bash
python scripts/build_json_report.py \
    --work-dir /tmp/video_work \
    --output ./output_report.json \
    --visual-timeline '[{"timestamp":"00:00:00","description":"Host enters frame."}]' \
    --character-names '{"1":"Host","2":"Guest"}' \
    --summary "Brief summary of the video." \
    --key-observations '["Key point A", "Key point B"]'
```

---

## Parameters

| Flag | Default | Description |
|------|---------|-------------|
| `--fps` | *(adaptive)* | Legacy override: force fixed-fps extraction (e.g. `--fps 0.5`). If omitted, adaptive scene-change sampling is used automatically. |
| `--max-frames` | `30` | Cap on frames when `--fps` is explicit. Adaptive mode uses its own internal cap (60). |
| `--model` | `large-v3-turbo` | Whisper model: `tiny` / `base` / `small` / `medium` / `large-v3-turbo` |
| `--similarity-threshold` | `0.72` | Character clustering sensitivity (0–1) |
| `--cross-verify` | *(off)* | Run a second Whisper decoding pass on low-confidence segments. Where both passes agree the flag is cleared; where they diverge the segment is marked `[trascrizioni discordanti]`. Cost: extra local CPU/GPU time proportional to the number of uncertain segments. Off by default. |
| `--batch-size` | `10` | `detect_characters.py` only. Frames per Vision API call for character detection. |
| `--language` | `None` (auto-detect) | Lingua audio per Whisper. Se non specificata, rilevamento automatico |
| `--task` | `transcribe` | `transcribe` mantiene la lingua originale; `translate` traduce in inglese |

---

## Scripts

| Script | Purpose |
|--------|---------|
| `process_video.py` | Estrazione frame event-driven, audio Whisper, Vision batch |
| `detect_characters.py` | Per-frame character tracking: Vision detection (Pass 1) + Python aggregation (Pass 2) |
| `cluster_frames.py` | Clustering HSV histogram → scene grouping |
| `build_json_report.py` | Assembly JSON v2.0 con RAG timeline, semantic compression e global index |
| `build_pdf_report.py` | Generazione PDF con thumbnail grid e timeline visiva |

---

## Output Format

| File | Formato | Destinatario | Contenuto chiave |
|------|---------|--------------|-----------------|
| `*_report.md` | Markdown | Lettura umana | Timeline visiva narrativa, summary, trascrizione |
| `*_report.json` | JSON | LLM / Vector DB | RAG timeline, global index, nodi con embedding hint |
| `*_report.pdf` | PDF | Condivisione/archivio | Thumbnail grid (con API key), tabelle, timeline |

---

## JSON Schema (v2.0)

```json
{
  "schema_version": "2.0",
  "generated_by": "video-analyzer skill",
  "disclaimers": {
    "audio": "Testo trascritto da Whisper: verificabile riascoltando il video originale.",
    "vision": "Descrizioni visive generate dal modello Vision su singoli fotogrammi: inferenza automatica, può contenere errori."
  },
  "metadata": {
    "filename": "video.mp4",
    "duration_seconds": 120.0,
    "duration_formatted": "00:02:00",
    "size_mb": 15.4,
    "video_codec": "h264",
    "width": 1920,
    "height": 1080,
    "fps_original": 30.0,
    "audio_codec": "aac",
    "language_detected": "it",
    "language_forced": false,
    "language_detection_prob": 0.87,
    "whisper_model": "large-v3-turbo",
    "vision_model": "claude-haiku-4-5-20251001"
  },
  "global_index": [
    {
      "cluster_id": "c_00",
      "ts_range": ["00:00:00.000", "00:01:40.000"],
      "summary": "First 100 chars of the cluster opening node…",
      "node_ids": ["n_0000", "n_0001", "n_0002"]
    }
  ],
  "characters": {
    "count": 2,
    "count_source": "claude_vision",
    "list": [
      {
        "character_id": 1,
        "name": "<Name> - <description>",
        "first_seen": "00:01:00",
        "appearances": ["00:01:00", "00:03:30", "00:07:00"]
      }
    ]
  },
  "rag_timeline": [
    {
      "node_id": "n_0000",
      "anchor_ts": "00:00:02.400",
      "window_ms": [2400, 6800],
      "text_raw": "Hello and welcome to the show.",
      "text_clean": "Hello and welcome to the show.",
      "visual_delta": "Host enters frame, blue studio backdrop.",
      "visual_delta_ts": "00:00:03",
      "source": "audio",
      "keywords": ["welcome", "show", "host"],
      "embedding_hint": "welcome show host. Hello and welcome to the show."
    }
  ],
  "audio": {
    "has_audio": true,
    "language_detected": "it",
    "language_forced": false,
    "language_detection_prob": 0.87,
    "language_note": "rilevata automaticamente: it (87%)",
    "transcript_segments": [
      {
        "timestamp": "00:00:02",
        "text": "Hello and welcome.",
        "avg_logprob": -0.3124,
        "no_speech_prob": 0.021,
        "confidence": 0.8438,
        "low_confidence": false,
        "source": "audio"
      },
      {
        "timestamp": "00:03:47",
        "text": "[trascrizioni discordanti] parole incerte originali",
        "avg_logprob": -0.891,
        "no_speech_prob": 0.183,
        "confidence": 0.555,
        "low_confidence": true,
        "source": "audio",
        "second_pass_text": "testo molto diverso dalla prima passata",
        "agreement": false,
        "similarity_score": 0.3241
      }
    ]
  },
  "visual_timeline": [
    {
      "timestamp": "00:00:00",
      "description": "Intro screen with title card.",
      "source": "vision"
    }
  ],
  "summary": "Video summary.",
  "key_observations": ["Observation A"]
}
```

**Key v2.0 additions vs v1.0:**
- `global_index` — hierarchical 10-node clusters for fast coarse retrieval
- `rag_timeline` — each node carries `text_clean`, `keywords`, `embedding_hint`, `visual_delta`, and `visual_delta_ts`
- `whisper_model` and `vision_model` tracked dynamically in metadata (not hardcoded)
- `language_detected` auto-detected by Whisper (overridable via `--language`); `language_forced`, `language_detection_prob`, and `language_note` expose detection confidence
- `disclaimers` top-level key distinguishes transcript (verifiable) from Vision descriptions (inference)
- `"source": "audio" | "vision"` on every element at all three levels (segments, timeline, nodes)
- `visual_delta_ts` — exact frame timestamp stored alongside `visual_delta` for precise Vision anchoring
- Nodes anchored to Whisper segments (event-driven) rather than fixed-fps intervals
- Near-duplicate segment merging with Jaccard threshold 0.85
- Adaptive scene-change frame sampling via `cv2.absdiff` — no `--fps` configuration required; frame density follows content automatically
- Whisper confidence scoring on every `transcript_segment`: `avg_logprob`, `no_speech_prob`, `confidence` (0–1 normalised), `low_confidence` bool
- `detect_characters.py` — optional per-frame character tracking via two-pass approach:
  Vision API (Pass 1) + pure Python chronological aggregation (Pass 2). Populates
  `first_seen` and `appearances` on each character; `"n/d"` when step is skipped.
- `--cross-verify` — optional second Whisper decoding pass (beam_size=1, temperature=0.2)
  on `low_confidence` segments only. Adds `second_pass_text`, `agreement`, `similarity_score`
  per verified segment. Cost: local CPU/GPU time only (no API). Off by default.

---

## Technical Notes

### Whisper large-v3-turbo
The default model reduces decoder layers from 32 to 4 for significantly faster transcription with negligible accuracy loss versus `large-v3`. Multilingual support fully integrated. Translation to English available via `--task translate`. Requires ~6 GB RAM during inference — confirmed working on 16 GB systems. First run downloads ~1.6 GB to `~/.cache/whisper/`.

### Vision batch
When `ANTHROPIC_API_KEY` is set, `process_video.py` batches scene-change frames (up to 20 per call) into the configured Vision model (`--vision-model`, default `claude-haiku-4-5-20251001`) and writes descriptions into `visual_delta` on each node. Without the key, `visual_delta` remains `null` and the PDF renders text-only. Set the key in your environment before running for full visual analysis.

### Adaptive frame sampling
`process_video.py` uses an **automatic adaptive sampler** — no configuration required:

1. **Pre-scan pass** — reads the video at 0.25 s intervals using 160×90 greyscale thumbnails and computes `cv2.absdiff` between consecutive frames.
2. **Selection logic** — a frame timestamp is selected when the normalised mean pixel-difference exceeds `SCENE_CHANGE_THRESHOLD = 0.30`, *or* when `MIN_FRAME_INTERVAL_SEC = 30` s have elapsed since the last saved frame (floor guarantee for static content). Total frames are hard-capped at `MAX_FRAMES_CAP = 60`.
3. **Extraction pass** — selected timestamps are re-opened at full resolution, scaled to ≤ 1568 px long edge, and written as JPEG (quality 85).

Result: a static 2-hour lecture → a handful of frames; a fast-cut music video → many frames up to the cap. The density follows the content automatically.

**Legacy mode**: pass `--fps 0.5` (or any value) to revert to fixed-fps ffmpeg extraction. A `WARNING` is logged and adaptive sampling is skipped for that run.

**Graceful degradation**: if `cv2` fails to open the video (unsupported codec, corrupted file), the sampler falls back automatically to fixed 0.5 fps via ffmpeg and logs the fallback. The pipeline never crashes.

### PDF rendering
`build_pdf_report.py` tries `weasyprint` first (full CSS layout, base64-embedded thumbnail grid). On Windows or systems without GTK, it falls back to `reportlab`. Thumbnails are embedded only when Vision has populated `visual_timeline` entries — without `ANTHROPIC_API_KEY`, the PDF contains text, tables, and keyword badges only.

### Confidence scoring
For each Whisper segment, `process_video.py` extracts `avg_logprob` (mean per-token log-probability) and `no_speech_prob` and derives a normalised `confidence` score:

```
confidence = clamp(1.0 + avg_logprob / 2.0, 0.0, 1.0)
```

This maps Whisper's practical range (0.0 → −2.0) linearly to [1.0, 0.0]. Segments with `confidence < 0.40` (constant `LOW_CONFIDENCE_THRESHOLD` in `process_video.py`) receive `"low_confidence": true` in the JSON. The transcribed **text is never modified** — the flag is annotation only, for human review.

Confidence fields are stored in `transcript_segments.json` and forwarded to `audio.transcript_segments` in the final JSON report. Segments from old runs (no `transcript_segments.json`) fall back to the `.txt` parsing path with `low_confidence: null`.

Low-confidence segments appear in italic with a `⚠️ [trascrizione incerta]` badge in the `.md` report and with grey/italic styling in the PDF.

### Cross-verification (--cross-verify)

When `--cross-verify` is passed, `process_video.py` runs a second independent Whisper
decoding pass **exclusively on segments already flagged `low_confidence = True`**.
Segments with `low_confidence = False` are never touched — zero extra compute for them.

**How it works:**

1. The audio slice for each uncertain segment is extracted via numpy array indexing
   (no disk I/O — the audio array is already in memory from the language detection pass).
2. A second `model.transcribe()` call runs on the slice with different decoding parameters:
   `beam_size=1` (greedy) and `temperature=0.2` versus `beam_size=5, temperature=0` for
   the first pass. The parameter difference maximises independence between the two passes.
3. Both outputs are compared using normalised character-level edit distance
   (`AGREEMENT_THRESHOLD = 0.75`).

**Outcomes per segment:**

| Result | Condition | Effect |
|--------|-----------|--------|
| Agreed | similarity ≥ 0.75 | `low_confidence` cleared (verification passed) |
| Discordant | similarity < 0.75 | text prepended with `[trascrizioni discordanti]`, flag retained |
| Failed | second pass raises exception | original flag kept, error logged, no crash |

**Cost:** Whisper runs locally — no API calls, no token cost. The overhead is **local
CPU/GPU time**: roughly one extra decode per low-confidence segment. On CPU-only machines
this is the dominant cost; on GPU machines the overhead is smaller. For most use cases
the first pass is sufficient; use `--cross-verify` when transcript accuracy on uncertain
segments is critical.

**New fields** (present only on cross-verified segments):

| Field | Type | Meaning |
|-------|------|---------|
| `second_pass_text` | string | Raw output of the second pass (audit only — not the authoritative transcript) |
| `agreement` | bool | `true` when similarity ≥ 0.75 |
| `similarity_score` | float | Normalised edit distance, 4 decimal places |

### Language detection transparency
After transcription, `process_video.py` runs `model.detect_language()` on the first 30 s of audio (encoder-only pass — negligible cost) to obtain a per-language probability. Three fields are written to `metadata.json` and forwarded to the `audio` section of the final report:

| Field | Type | Meaning |
|-------|------|---------|
| `language_detected` | string | ISO code detected by Whisper (e.g. `"it"`) |
| `language_forced` | bool | `true` when `--language` was passed explicitly |
| `language_detection_prob` | float \| null | Probability [0–1] for the detected language; `null` if forced or detection failed |
| `language_note` | string | Human-readable summary, e.g. `"rilevata automaticamente: it (87%)"` or `"bassa confidenza, verificare"` for prob < 60% |

The language note is displayed in the PDF metadata table, the transcript summary banner, and the `.md` report header.

### Source attribution
Every element in the JSON report carries `"source": "audio" | "vision"`:
- `"audio"` — text derived from Whisper transcription (verifiable by re-listening)
- `"vision"` — description generated by Claude Vision on a single frame (AI inference, may contain errors)

The PDF renders source badges — `[🎤 audio]` in green and `[👁 visione]` in purple — throughout the timeline and transcript sections. A one-time disclaimer callout in the PDF header explains the distinction. The `.md` report prefixes Vision descriptions with `> 👁 [descrizione automatica immagine]`.

### Semantic compression
`build_json_report.py` applies three passes before writing the final JSON:
1. **Filler removal** — context-aware regex removes Italian verbal fillers (`uhm`, `cioè`, `tipo`, etc.) only before punctuation or articles, preserving semantic use
2. **Segment merging** — adjacent nodes with same scene (`visual_delta: null`), gap < 1500ms, and combined length < 800 chars are merged into one
3. **Near-duplicate removal** — segments with Jaccard similarity ≥ 0.85 are deduplicated, keeping the richer `visual_delta`

---

## License

This project is open-source and available under the [MIT License](LICENSE).

---

## Contributing

Issues and PRs welcome. If you add support for a new output format or improve character detection (e.g. face embeddings), please open a PR.

To submit to the official Anthropic skills directory:

```bash
# Fork https://github.com/anthropics/skills
# Copy the video-analyzer/ folder into skills/
# Open a pull request
```
