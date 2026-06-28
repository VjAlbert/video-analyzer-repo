#!/usr/bin/env python3
"""
detect_characters.py — Per-frame character tracking for the video-analyzer skill.

Runs between process_video.py and build_json_report.py. Resolves the "n/d"
first_seen / appearances fields that build_json_report.py writes when no
per-frame character data is available.

Usage:
    python3 detect_characters.py \
        --work-dir /tmp/video_work \
        --character-names '{"1":"<Name> - <description>","2":"<Name> - <description>"}' \
        --vision-model claude-haiku-4-5-20251001 \
        --batch-size 10

Two-pass approach:
    Pass 1 — local detection: one Vision API call per batch of frames, asking
             which catalog character IDs are visible in each image.
    Pass 2 — programmatic aggregation (zero API calls): walk the frames in
             chronological (manifest) order to derive first_seen + appearances.

Output (inside --work-dir):
    character_appearances.json — { "<id>": {"first_seen": "...", "appearances": [...]}, ... }
                                 Only IDs actually observed in at least one frame are included.
"""

import argparse
import json
import os
import re
import sys
from collections import OrderedDict

# Ensure stdout/stderr can render non-ASCII output on Windows (cp1252).
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# ── Args ─────────────────────────────────────────────────────────────────────
parser = argparse.ArgumentParser()
parser.add_argument("--work-dir", default="/tmp/video_work",
                    help="Working directory produced by process_video.py")
parser.add_argument("--character-names", default="{}",
                    help="JSON object mapping character_id (str) to 'Name - description'")
parser.add_argument("--vision-model", default="claude-haiku-4-5-20251001",
                    help="Claude model used for character detection (default claude-haiku-4-5-20251001)")
parser.add_argument("--batch-size", type=int, default=10,
                    help="Number of frames sent per Vision API call (default 10)")
args = parser.parse_args()

BATCH_SIZE = max(1, args.batch_size)


# ── File I/O helper (same pattern as build_json_report.py) ─────────────────────
def read_json(path):
    if os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError, UnicodeDecodeError) as e:
            print(f"    WARNING: could not read {path}: {e}", flush=True)
            return {}
    return {}


def _char_sort_key(item):
    return int(item[0]) if item[0].isdigit() else 0


# ── Parse character catalog ───────────────────────────────────────────────────
# --character-names is always dynamic (user-provided). Nothing about specific
# IDs, names, or descriptions is hardcoded here.
_cn_raw = args.character_names.strip()
if not _cn_raw:
    print("No characters provided, skipping.", flush=True)
    sys.exit(0)
try:
    character_names = json.loads(_cn_raw)
except json.JSONDecodeError as e:
    print(f"ERROR: --character-names is not valid JSON: {e}", flush=True)
    sys.exit(1)
if not isinstance(character_names, dict) or not character_names:
    print("No characters provided, skipping.", flush=True)
    sys.exit(0)

# ── Read manifest ─────────────────────────────────────────────────────────────
manifest_path = os.path.join(args.work_dir, "manifest.json")
manifest = read_json(manifest_path)
if not isinstance(manifest, list) or not manifest:
    print(f"ERROR: manifest.json missing or empty at {manifest_path}", flush=True)
    sys.exit(1)

# ── Build character catalog string ─────────────────────────────────────────────
# Split each value on " - " (first occurrence only) into name + description.
catalog_lines = []
for cid, value in sorted(character_names.items(), key=_char_sort_key):
    value = value or ""
    if " - " in value:
        name, desc = value.split(" - ", 1)
    else:
        name, desc = value, ""
    catalog_lines.append(f"- ID {cid}: {name.strip()} — {desc.strip()}".rstrip(" —").rstrip())
catalog = "\n".join(catalog_lines)

# ── Vision setup (anthropic import inside try/except, same as process_video.py) ─
_vision_ready = False
_anthropic_client = None
_b64 = None

try:
    import anthropic as _anthropic_mod
    import base64 as _b64_mod
    _b64 = _b64_mod
    _api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if _api_key:
        _anthropic_client = _anthropic_mod.Anthropic(api_key=_api_key)
        _vision_ready = True
    else:
        print("    ANTHROPIC_API_KEY not set — skipping character detection", flush=True)
except ImportError:
    print("    anthropic package not installed — skipping character detection", flush=True)

# Do not crash the outer pipeline when Vision is unavailable.
if not _vision_ready:
    sys.exit(0)

DETECT_PROMPT = (
    "Catalogo personaggi noti:\n"
    f"{catalog}\n"
    "\n"
    "Per ogni immagine fornita in ordine, elenca ONLY gli ID dei personaggi dal catalogo\n"
    "che sono chiaramente visibili nell'immagine.\n"
    "Se nessun personaggio del catalogo e' visibile, scrivi \"nessuno\".\n"
    "Formato obbligatorio (rispetta esattamente):\n"
    "IMAGE_1: <id>,<id> | IMAGE_2: nessuno | IMAGE_3: <id> | ...\n"
    "Non aggiungere testo extra fuori dal formato."
)

# ── Pass 1 — local detection (one API call per batch) ──────────────────────────
total = len(manifest)
num_batches = (total + BATCH_SIZE - 1) // BATCH_SIZE
print(f"[1/2] Detecting characters in {total} frame(s) across {num_batches} batch(es) …", flush=True)

frame_results = {}  # manifest_idx -> list of character ID strings

for batch_num, batch_start in enumerate(range(0, total, BATCH_SIZE)):
    batch = manifest[batch_start:batch_start + BATCH_SIZE]

    # Map each manifest entry in this batch to its frame on disk.
    valid_items = []  # (manifest_idx, frame_path)
    for offset, entry in enumerate(batch):
        midx = batch_start + offset
        path = entry.get("path", "")
        if path and os.path.exists(path):
            valid_items.append((midx, path))
        else:
            print(f"    WARNING: frame not found on disk, skipping: {path}", flush=True)

    if not valid_items:
        continue

    # Build API message: images first (in order), text prompt last.
    content = []
    for _, frame_path in valid_items:
        with open(frame_path, "rb") as fimg:
            b64_data = _b64.standard_b64encode(fimg.read()).decode("utf-8")
        content.append({
            "type": "image",
            "source": {"type": "base64", "media_type": "image/jpeg", "data": b64_data},
        })
    content.append({"type": "text", "text": DETECT_PROMPT})

    try:
        msg = _anthropic_client.messages.create(
            model=args.vision_model,
            max_tokens=max(512, len(valid_items) * 40),
            messages=[{"role": "user", "content": content}],
        )
        if msg.stop_reason == "max_tokens":
            print(f"    WARNING: detection response truncated (max_tokens reached) "
                  f"— some frames may be unresolved.", flush=True)
        response_text = msg.content[0].text

        # Parse "IMAGE_N: id,id | IMAGE_N+1: nessuno | ..." — use findall so the loop
        # works regardless of whether the model separates entries with pipes or newlines.
        _NO_CHAR_TOKENS = {"nessuno", "none", "n/a", "-", "–", "nessun"}
        detections = {}
        for m_parse in re.finditer(r"IMAGE_(\d+):\s*([^\|]+)", response_text, re.IGNORECASE):
            idx = int(m_parse.group(1)) - 1  # 0-indexed within the batch
            if idx >= 0:
                detections[idx] = m_parse.group(2).strip()

        for batch_idx, (midx, _) in enumerate(valid_items):
            value = detections.get(batch_idx, "")
            ids = []
            for tok in value.split(","):
                tok = tok.strip()
                if tok and tok.lower() not in _NO_CHAR_TOKENS:
                    ids.append(tok)
            frame_results[midx] = ids

        resolved = sum(1 for batch_idx in range(len(valid_items)) if batch_idx in detections)
        print(f"    Batch {batch_num + 1}/{num_batches}: {len(valid_items)} frame(s) → {resolved} parsed", flush=True)

    except Exception as e:
        # Batch failed: leave those frames unresolved and carry on with the next batch.
        print(f"    Batch {batch_num + 1}/{num_batches} failed: {e} — frames left unresolved", flush=True)
        continue

# ── Pass 2 — programmatic aggregation (zero API calls) ─────────────────────────
print("[2/2] Aggregating appearances in chronological order …", flush=True)
character_appearances = OrderedDict()

for midx in range(total):
    ids = frame_results.get(midx, [])
    if not ids:
        continue
    ts = manifest[midx].get("timestamp_formatted", "")
    for cid in ids:
        # Ignore IDs the model invented that are not in the provided catalog.
        if cid not in character_names:
            continue
        if cid not in character_appearances:
            character_appearances[cid] = {"first_seen": ts, "appearances": []}
        character_appearances[cid]["appearances"].append(ts)

# ── Write output ───────────────────────────────────────────────────────────────
out_path = os.path.join(args.work_dir, "character_appearances.json")
with open(out_path, "w", encoding="utf-8") as f:
    json.dump(character_appearances, f, indent=2, ensure_ascii=False)

print(f"✅ Character tracking complete → {out_path}", flush=True)
print(f"   Characters in catalog : {len(character_names)}", flush=True)
print(f"   Characters observed   : {len(character_appearances)}", flush=True)
for cid, data in character_appearances.items():
    print(f"   ID {cid}: first_seen {data['first_seen']}  |  {len(data['appearances'])} appearance(s)", flush=True)
