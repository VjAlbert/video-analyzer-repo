# Contributing to video-analyzer

Thanks for your interest! Here's how to contribute.

## Quick start

```bash
git clone https://github.com/<your-username>/video-analyzer
cd video-analyzer
pip install openai-whisper opencv-python-headless numpy Pillow
# make sure ffmpeg is on PATH
```

## Testing a change

Upload any video and run manually from the repository root:

```bash
# Run preprocessing (adaptive sampling — no --fps needed)
python3 scripts/process_video.py /path/to/test.mp4 \
    --output-dir /tmp/test_work --model large-v3-turbo

# Run visual scene clustering (checks color/composition similarity)
python3 scripts/cluster_frames.py \
    --frames-dir /tmp/test_work/frames \
    --output /tmp/test_work/clusters.json \
    --manifest /tmp/test_work/manifest.json

# Check the generated intermediate data
cat /tmp/test_work/metadata.json              # includes language_detected, language_forced, language_detection_prob
cat /tmp/test_work/transcript_segments.json   # confidence scores per segment (avg_logprob, confidence, low_confidence, source)
cat /tmp/test_work/intermediate_nodes.json    # pivot nodes with visual_delta_ts and source fields
cat /tmp/test_work/clusters.json
```

Then build the full report and check outputs:

```bash
python3 scripts/build_json_report.py \
    --work-dir /tmp/test_work \
    --output /tmp/test_work/report.json \
    --visual-timeline '[]' --character-names '{}' \
    --summary "Test." --key-observations '[]'
```

**What to verify in the final report:**

- `report["disclaimers"]` — both `audio` and `vision` keys present
- `report["audio"]["language_note"]` — human-readable string (e.g. `"rilevata automaticamente: it (87%)"`)
- `report["audio"]["language_detection_prob"]` — float or `null` (only `null` when `--language` was forced)
- Every `rag_timeline` node has `"source": "audio"`; nodes with a Vision description also have `"visual_delta_ts"`
- Every `audio.transcript_segments` entry has `"source": "audio"`, `"low_confidence"` bool or `null`
- Every `visual_timeline` entry has `"source": "vision"`
- In the PDF: `[🎤 audio]` badge on transcript lines, `[👁 visione]` badge on Vision descriptions, language note in metadata table and transcript banner, per-row timestamps throughout

## Coding conventions

- No new dependencies — every feature must degrade gracefully when optional packages are absent
- Transcript text is never modified — confidence flags, source badges, and language notes are annotation-only
- All timestamps use `HH:MM:SS` (8-char) format in output; `HH:MM:SS.mmm` internally in `anchor_ts`
- `"source"` field is always set at write time, never inferred later
