#!/usr/bin/env python3
"""
build_json_report.py — Assembles the final JSON report for the video-analyzer skill.

Usage:
    python3 build_json_report.py \
        --work-dir /tmp/video_work \
        --output /path/to/output.json \
        --visual-timeline '[{"ts":"00:00:00","desc":"..."}]'   # JSON string from Claude
        --character-names '{"1":"Gioggia","2":"Antoni"}'       # optional, from Claude's vision pass
        --summary "Overall summary text"

Reads: metadata.json, transcript.txt, clusters.json (optional), manifest.json
Characters and their count come from Claude Vision (passed via --character-names).
clusters.json is optional; if absent, the characters section is populated from
--character-names alone.
Outputs: single structured JSON file
"""
import argparse
import json
import os

parser = argparse.ArgumentParser()
parser.add_argument("--work-dir", default="/tmp/video_work")
parser.add_argument("--output", required=True)
parser.add_argument("--visual-timeline", default="[]",
                    help="JSON array of {timestamp, description} from Claude's vision pass")
parser.add_argument("--character-names", default="{}",
                    help="JSON object mapping character_id (str) to name")
parser.add_argument("--summary", default="")
parser.add_argument("--key-observations", default="[]",
                    help="JSON array of observation strings")
args = parser.parse_args()

# ── Read all sources ──────────────────────────────────────────────────────────
def read_json(path):
    if os.path.exists(path):
        with open(path) as f:
            return json.load(f)
    return {}

def read_text(path):
    if os.path.exists(path):
        with open(path) as f:
            return f.read().strip()
    return ""

metadata    = read_json(os.path.join(args.work_dir, "metadata.json"))
manifest    = read_json(os.path.join(args.work_dir, "manifest.json"))
clusters    = read_json(os.path.join(args.work_dir, "clusters.json"))
transcript_raw = read_text(os.path.join(args.work_dir, "transcript.txt"))

# Parse transcript into structured segments
transcript_segments = []
if transcript_raw and transcript_raw not in ("NO_AUDIO", "") and not transcript_raw.startswith("TRANSCRIPTION_ERROR"):
    for line in transcript_raw.splitlines():
        line = line.strip()
        if line.startswith("[") and "]" in line:
            bracket_end = line.index("]")
            ts = line[1:bracket_end]
            text = line[bracket_end+1:].strip()
            transcript_segments.append({"timestamp": ts, "text": text})

# Parse optional inputs
visual_timeline = json.loads(args.visual_timeline) if args.visual_timeline else []
character_names = json.loads(args.character_names) if args.character_names else {}
key_observations = json.loads(args.key_observations) if args.key_observations else []

# Build character list from Claude Vision names (--character-names).
# Empty dict means either "skipped" or "zero characters found" — both yield an empty list.
# Cluster data is a frame-selection aid only; it does not identify characters.
char_list = []
if character_names:
    for cid_str, name in sorted(character_names.items(), key=lambda x: int(x[0]) if x[0].isdigit() else 0):
        char_list.append({"character_id": int(cid_str) if cid_str.isdigit() else cid_str, "name": name})

# ── Assemble report ───────────────────────────────────────────────────────────
report = {
    "schema_version": "1.0",
    "generated_by": "video-analyzer skill",
    "metadata": metadata,
    "characters": {
        "count": len(char_list),
        "count_source": "claude_vision" if character_names else "not_provided",
        "list": char_list,
    },
    "audio": {
        "has_audio": bool(transcript_segments),
        "language_detected": metadata.get("language_detected", "unknown"),
        "transcript_segments": transcript_segments,
    },
    "visual_timeline": visual_timeline,
    "summary": args.summary,
    "key_observations": key_observations,
    "frames": {
        "total_extracted": len(manifest) if isinstance(manifest, list) else 0,
        "manifest": manifest if isinstance(manifest, list) else [],
    }
}

with open(args.output, "w", encoding="utf-8") as f:
    json.dump(report, f, indent=2, ensure_ascii=False)

print(f"✅ JSON report written to {args.output}")
print(f"   Characters : {report['characters']['count']} ({report['characters']['count_source']})")
print(f"   Transcript : {len(transcript_segments)} segments")
print(f"   Timeline   : {len(visual_timeline)} entries")
