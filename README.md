# video-analyzer (Claude Skill)

> Converts any video file into a comprehensive AI-readable report **(Markdown + JSON + PDF)** with RAG-ready timeline, Vision scene analysis, and semantic compression.

This Claude Skill bridges LLM environments that do not natively support direct video uploads (such as Claude Projects). It extracts audio transcripts via Whisper, identifies visual scene changes, and structures all data into a pivot format (`intermediate_nodes.json`) consumed by downstream report generators.

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

> ⚠️ **Nota su large-v3-turbo**: il modello Whisper viene scaricato automaticamente al primo run (~1.6 GB). Assicurati di avere connessione e spazio disco disponibile prima del primo utilizzo.

### Cowork Desktop

1. Apri Cowork → Settings → Skills → Upload
2. Trascina la cartella `video-analyzer/` completa (non solo `SKILL.md`)
3. La skill sarà disponibile nella sessione corrente

### Claude.ai Desktop / Web (read-only mode)

Claude.ai non supporta l'esecuzione di script Python o ffmpeg. Puoi caricare `SKILL.md` come istruzione personalizzata in un Claude Project per documentazione e reference, ma l'esecuzione completa richiede Claude Code o Cowork.

---

## Requirements

```
Auto-installati al primo run:
- ffmpeg                   (deve essere sul PATH di sistema — verifica con: ffmpeg -version)
- openai-whisper           (modello default: large-v3-turbo, ~1.6 GB al primo download)
- opencv-python-headless
- numpy, Pillow
- reportlab                (PDF renderer — fallback se weasyprint non disponibile)
```

```bash
pip install openai-whisper opencv-python-headless numpy Pillow reportlab
```

> **Windows**: `weasyprint` richiede GTK e non è nativo su Windows. Il fallback `reportlab` viene usato automaticamente.

---

## Architecture v2.0

Pipeline a tre stadi con formato pivot intermedio:

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
| `--language` | `None` (auto-detect) | Lingua audio per Whisper. Se non specificata, rilevamento automatico |
| `--task` | `transcribe` | `transcribe` mantiene la lingua originale; `translate` traduce in inglese |

---

## Scripts

| Script | Purpose |
|--------|---------|
| `process_video.py` | Estrazione frame event-driven, audio Whisper, Vision batch |
| `cluster_frames.py` | Clustering HSV histogram → character count |
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
    "vision": "Descrizioni visive generate da Claude Vision su singoli fotogrammi: inferenza automatica, può contenere errori."
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
      { "character_id": 1, "name": "Host" }
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

---

## Technical Notes

### Whisper large-v3-turbo
The default model reduces decoder layers from 32 to 4 for significantly faster transcription with negligible accuracy loss versus `large-v3`. Multilingual support fully integrated. Translation to English available via `--task translate`. Requires ~6 GB RAM during inference — confirmed working on 16 GB systems. First run downloads ~1.6 GB to `~/.cache/whisper/`.

### Vision batch
When `ANTHROPIC_API_KEY` is set, `process_video.py` batches scene-change frames (up to 20 per call) into Claude Vision and writes descriptions into `visual_delta` on each node. Without the key, `visual_delta` remains `null` and the PDF renders text-only. Set the key in your environment before running for full visual analysis.

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
