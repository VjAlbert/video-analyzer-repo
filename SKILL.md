---
name: video-analyzer
description: >
  Analyze a video file and produce a comprehensive AI-readable report (Markdown + JSON).
  Use this skill whenever the user uploads or references a video file (.mp4, .mov, .avi,
  .mkv, .webm, .m4v) and wants to: understand its content, create a report from it,
  extract what is said or shown, describe what happens, count or identify characters,
  summarize the video for use in a Claude project (where direct MP4 upload is not
  supported), or generate any written analysis of video content.
  Trigger even for casual phrasing like "what's in this video", "read this mp4",
  "make a report from this video", "transcribe this video", "describe this clip",
  "how many characters are in this video", "who appears in this video".
compatibility: >
  bash_tool (ffmpeg, Python 3.x), view tool (image inspection), Anthropic Vision API.
  Required pip packages: openai-whisper, opencv-python-headless, numpy, Pillow.
---

# Video Analyzer Skill

Converts a video file into a complete, structured report (Markdown, JSON **and** PDF) that
captures everything an AI or human needs to understand the video without watching it.
Includes audio transcription (Whisper), visual frame analysis (Claude Vision), and
optional scene clustering to aid frame selection.

---

## Installation

### Claude Code / Cowork (full execution)

```bash
pip install openai-whisper opencv-python-headless numpy Pillow \
    --break-system-packages -q 2>/dev/null || true

# PDF renderer — install one (weasyprint preferred, reportlab as fallback):
pip install weasyprint      # requires GTK3 on Linux/macOS
pip install reportlab       # pure Python, works everywhere
```

Running `build_json_report.py` automatically generates **MD + JSON + PDF** in a single
invocation. No separate command is needed for the PDF.

### Claude.ai Desktop / Web (read-only mode)

Upload `SKILL.md` as an instruction file in a Claude Project. The skill will describe
the analysis process and interpret pre-generated JSON/MD reports, but **cannot execute**
`ffmpeg`, Whisper, or the Python scripts without Claude Code or Cowork.
For full execution (frame extraction, transcription, PDF generation) use Claude Code.

### Customising the PDF template

The CSS and HTML layout live entirely inside `scripts/build_pdf_report.py` — no
external stylesheets or assets. To customise colours, fonts, or sections:
1. Edit the `_CSS` string constant near the top of the file.
2. Edit the `_build_html()` function for structural changes (sections, order).
3. Edit `_build_pdf_reportlab()` for the reportlab fallback layout.

The `generate_pdf(json_path, frames_dir, output_dir)` function is the stable public
API — call it from any script without touching the internals.

**Token cost estimates** (choose your mode):
- **Character-counting pass only** (5–8 frames): ~8–12k vision tokens
- **Full frame-by-frame timeline** (up to 30 frames): ~40k+ vision tokens

---

## Step 0 — Find the video file

```bash
ls /mnt/user-data/uploads/
```

If no video is present, ask the user to upload via the 📎 icon.

---

## Step 1 — Install dependencies & run pre-processing

```bash
pip3 install openai-whisper opencv-python-headless numpy Pillow \
    --break-system-packages -q 2>/dev/null || true

python3 /home/claude/video-analyzer/scripts/process_video.py \
    "<VIDEO_PATH>" \
    --output-dir /tmp/video_work \
    --model large-v3-turbo
```

Frame sampling is **automatic and adaptive** — no configuration required.
`process_video.py` scans the video at 0.25 s intervals, measures visual change with
`cv2.absdiff`, and extracts a frame only when the scene changes significantly, or at
least every 30 s on static content (floor), capped at 60 frames (ceiling).
Frames are resized so the long edge is at most **1568 px** (aspect ratio preserved).

**Parameter guide:**

| Parameter | Default | When to change |
|-----------|---------|----------------|
| `--fps` | *(adaptive)* | Pass a value (e.g. `0.5`) **only** to force legacy fixed-fps extraction. A warning is logged and adaptive sampling is disabled for that run. |
| `--max-frames` | 30 | Applies only when `--fps` is explicit. Adaptive mode uses its own internal cap (60). |
| `--model` | large-v3-turbo | Whisper model: tiny/base/small/medium/large-v3-turbo |

---

## Step 2 — (Optional) Run visual scene clustering

This step groups frames by color/composition similarity to help you pick
representative frames for Claude Vision. It is **not** a character detector —
it uses HSV histograms, not face recognition. Skip this step if you prefer
to select frames manually.

```bash
python3 /home/claude/video-analyzer/scripts/cluster_frames.py \
    --frames-dir /tmp/video_work/frames \
    --output /tmp/video_work/clusters.json \
    --manifest /tmp/video_work/manifest.json \
    --similarity-threshold 0.72
```

The output `clusters.json` contains `visual_cluster_count` (a rough grouping
estimate) and a `representative_frame` path per cluster. Use these paths to
choose the 5–8 frames for the character-counting pass below.

**Tuning `--similarity-threshold`:**
- Too many clusters (>8 for a simple video): raise to 0.80
- Too few clusters (everything merged): lower to 0.60

---

## Step 3 — Read metadata, transcript, and cluster data

```bash
cat /tmp/video_work/metadata.json
cat /tmp/video_work/transcript.txt
cat /tmp/video_work/transcript_segments.json   # confidence scores per segment (avg_logprob, confidence, low_confidence)
cat /tmp/video_work/clusters.json   # omit if Step 2 was skipped
cat /tmp/video_work/manifest.json
```

---

## Step 4 — Identify characters with Claude Vision (character-counting pass)

Pick **5–8 well-distributed frames** from the manifest (or use the
`representative_frame` paths from `clusters.json`). Inspect each with the
`view` tool.

```
view: /tmp/video_work/frames/frame_0001.jpg
view: /tmp/video_work/frames/frame_0009.jpg
…
```

For each frame, note every **distinct person or character** visible: appearance,
clothing, setting. Then synthesize across all frames:

- How many distinct characters appear in total?
- Give each a short label and description (e.g. "Character 1 — Gioggia: blonde,
  white suit, office setting").

**This count and identification come from your visual judgment**, not from
the clustering script. The skill targets AI-generated and stylized video where
geometric face detectors are unreliable; a vision model reasoning about
"distinct characters" is more appropriate.

Record your findings:

```
Character 1: <name/label> — <description>
Character 2: <name/label> — <description>
…
```

---

## Step 5 — Full visual timeline (optional, ~40k+ tokens)

If the user wants a frame-by-frame timeline, sweep through all frames in the
manifest. Group near-identical consecutive frames and write a 2–4 sentence
description per distinct scene:

```
[00:00:00] <who is present, setting, action, any on-screen text>
[00:00:05] <…>
…
```

Skip this step for a summary-only report to keep token cost low.

---

## Step 6 — Build the JSON report

```bash
python3 /home/claude/video-analyzer/scripts/build_json_report.py \
    --work-dir /tmp/video_work \
    --output /mnt/user-data/outputs/<basename>_report.json \
    --visual-timeline '<JSON_ARRAY>' \
    --character-names '<JSON_OBJECT>' \
    --summary "<SUMMARY_TEXT>" \
    --key-observations '<JSON_ARRAY>'
```

Example values:
```
--visual-timeline '[{"timestamp":"00:00:00","description":"Donna bionda..."}]'
--character-names '{"1":"Gioggia","2":"Antoni","3":"Marina","4":"Anziano"}'
--summary "Video di satira politica AI-generated..."
--key-observations '["Prodotto con SHOWRUNNER.XYZ","4 personaggi distinti"]'
```

`--character-names` is the output of your Claude Vision identification pass
(Step 4). If you skipped Step 4 (summary-only), pass `{}`.

---

## Step 7 — Build the Markdown report

Save to `/mnt/user-data/outputs/<basename>_report.md` using this template.

**Confidence marking rules** (apply when writing Section 3):
- Read `audio.transcript_segments` from the JSON report (field `low_confidence` is bool or null).
- Count N = total segments, M = segments where `low_confidence == true`.
- For each segment:
  - `low_confidence: true`  → render the entire line in italic, prepend `⚠️ [trascrizione incerta]`
  - `low_confidence: false` → render normally
  - `low_confidence: null` or field absent → render normally but append `[confidenza non disponibile]`
- **Never alter or omit the transcribed text** — marking is purely presentational.

```markdown
# 📹 Video Report: <filename>
> Auto-generato dalla skill video-analyzer.

> **Trascrizione: N segmenti totali, M a bassa confidenza (da verificare manualmente)**
>
> **Nota sulle sorgenti:** Il testo in sezione 3 (🎤 audio) proviene dalla trascrizione
> Whisper ed è verificabile riascoltando il video. Le descrizioni in sezione 4
> (👁 visione) sono generate da Claude Vision su singoli fotogrammi: inferenza automatica,
> può contenere errori.

## 1. Metadata
| Proprietà | Valore |
|-----------|--------|
| Filename | `...` |
| Durata | `HH:MM:SS` |
| Risoluzione | `WxH` |
| Video codec | `...` |
| Audio codec | `...` |
| Dimensione | `N MB` |
| FPS | `N` |
| Bitrate | `N kbps` |
| Whisper model | `<metadata.whisper_model>` |
| Vision model | `<metadata.vision_model>` |

## 2. Personaggi Identificati
*(N personaggi distinti identificati da Claude Vision)*

| ID | Nome/Label | Descrizione |
|----|-----------|-------------|
| 1  | ...        | ...         |

## 3. Trascrizione Audio — 🎤 sorgente: Whisper (verificabile riascoltando il video)
*(N segmenti totali · M a bassa confidenza · Whisper `<metadata.whisper_model>` · Lingua: `<audio.language_note>`)*

> **Trascrizione: N segmenti totali, M a bassa confidenza (da verificare manualmente) · Lingua: `<audio.language_note>`**
>
> *(Se `audio.language_detection_prob` < 0.60, aggiungere: "⚠️ Rilevamento lingua incerto — se il video contiene più lingue o audio poco chiaro, la trascrizione può contenere errori sistematici.")*

[HH:MM:SS] Esempio di segmento normale con confidenza alta.
*⚠️ [trascrizione incerta] [HH:MM:SS] Esempio di segmento con low_confidence: true — testo originale invariato.*
[HH:MM:SS] Esempio di segmento senza campo confidence. [confidenza non disponibile]

## 4. Timeline Visiva — 👁 sorgente: Claude Vision (interpretazione automatica di fotogrammi)

> **Nota:** Le descrizioni seguenti sono generate da Claude Vision analizzando singoli
> fotogrammi estratti dal video. Si tratta di inferenza automatica: può contenere errori
> di identificazione, attribuzione o interpretazione. Non equivale alla trascrizione audio.

### [HH:MM:SS] — Scena N
> 👁 [descrizione automatica immagine] <descrizione 2-4 frasi di cosa Claude Vision vede nel frame>

## 5. Sommario AI
<150–300 parole>

## 6. Osservazioni Chiave
- ...
```

---

## Step 8 — Present both files

```python
present_files([
    "/mnt/user-data/outputs/<basename>_report.md",
    "/mnt/user-data/outputs/<basename>_report.json"
])
```

---

## Tips & edge cases

- **No audio**: set transcript to "No audio track detected."
- **Screen recordings**: pay attention to UI, on-screen text, window titles
- **Fast-cut video**: adaptive sampling handles this automatically; no flag needed
- **Very long (>30 min) static video**: the 30 s floor guarantees coverage; no flag needed
- **Override sampling**: pass `--fps 0.5` to revert to legacy fixed-fps mode (e.g. for debugging)
- **Foreign audio**: Whisper is multilingual, no configuration needed
- **AI-generated / animated video**: face detectors won't work; rely entirely on
  Claude Vision for character identification — this is the expected use case
- **Skip clustering entirely**: just pick frames evenly spaced from the manifest
  for the character-counting pass

---

## Scripts

| Script | Role |
|--------|------|
| `process_video.py` | Pre-processing: metadata → scene detection → audio → Whisper → `intermediate_nodes.json` |
| `cluster_frames.py` | Optional: groups scene frames by HSV similarity for representative frame selection |
| `build_json_report.py` | Semantic compression + global_index + JSON report; auto-calls `build_pdf_report.py` |
| `build_pdf_report.py` | PDF generator (weasyprint → reportlab fallback). Entry point: `generate_pdf(json, frames_dir, out_dir)` |

### Intermediate files

| File | Description |
|------|-------------|
| `metadata.json` | ffprobe metadata (duration, codec, resolution, …) |
| `manifest.json` | Frame paths and scene-change timestamps |
| `transcript.txt` | Whisper transcript with `[HH:MM:SS]` markers |
| `clusters.json` | Visual clusters from `cluster_frames.py` (optional) |
| `intermediate_nodes.json` | Formato pivot interno da cui vengono generati tutti gli output. Non eliminare tra le esecuzioni. |
| `transcript_segments.json` | Segmenti Whisper strutturati con punteggi di confidenza: `avg_logprob` (raw Whisper), `no_speech_prob`, `confidence` (normalizzata 0–1), `low_confidence` (bool). Letto da `build_json_report.py` per arricchire `audio.transcript_segments` nel JSON finale. Valori: `confidence` vicino a 1.0 = trascrizione affidabile; `low_confidence: true` = verificare manualmente. |
