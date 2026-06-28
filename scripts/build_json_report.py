#!/usr/bin/env python3
"""
build_json_report.py — Assembles the final JSON report for the video-analyzer skill.

Usage:
    python3 build_json_report.py \
        --work-dir /tmp/video_work \
        --output /path/to/output.json \
        --visual-timeline '[{"ts":"00:00:00","desc":"..."}]'
        --character-names '{"1":"Gioggia","2":"Antoni"}'
        --summary "Overall summary text"

Reads: intermediate_nodes.json (primary pivot), metadata.json, transcript.txt,
       clusters.json (optional), manifest.json

Processing pipeline applied to intermediate_nodes before assembly:
  A) text_raw → text_clean  (filler removal, duplicate-word collapse)
  B) Segment merging         (consecutive static nodes within gap/length thresholds)
  C) keyword extraction      (top-5 content words via Counter, Italian stopwords excluded)
  D) embedding_hint          (keywords + text_clean[:200], no API call)
  E) global_index            (10-node clusters with ts_range + summary)

Overwrites intermediate_nodes.json with the processed nodes, then writes the JSON report.
"""
import argparse
import json
import os
import re
import sys
from collections import Counter

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

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
parser.add_argument("--model", default="",
                    help="Override whisper_model in the report (e.g. 'base', 'large-v3-turbo')")
args = parser.parse_args()

# ── Text processing constants ──────────────────────────────────────────────────
ITALIAN_STOPWORDS = frozenset({
    # Articoli
    "il", "la", "le", "lo", "i", "gli", "l",
    "un", "una", "uno",
    # Preposizioni semplici e articolate
    "di", "del", "della", "dei", "degli", "delle",
    "dal", "dalla", "dai", "dagli", "dalle",
    "da", "in", "nel", "nella", "nei", "negli", "nelle",
    "a", "al", "alla", "ai", "agli", "alle",
    "con", "su", "sul", "sulla", "sui", "sugli", "sulle",
    "per", "tra", "fra",
    # Pronomi relativi e interrogativi
    "che", "chi", "cui",
    # Pronomi personali e clitici
    "non", "si", "mi", "ti", "ci", "vi", "ne", "li",
    "noi", "voi", "loro", "mio", "tuo", "suo",
    # Congiunzioni e particelle
    "è", "e", "ed", "ma", "però", "se", "o",
    "quando", "come", "anche", "ancora", "già", "poi",
    "più", "meno", "molto", "poco", "solo",
    # Verbi ausiliari e copulativi
    "ho", "hai", "ha", "hanno", "sono", "era", "sarà",
    "sto", "stai", "sta", "siamo", "state",
    "essere", "avere", "fare", "dire", "vedere", "andare",
    # Dimostrativi
    "questo", "questa", "questi", "queste",
    "quello", "quella", "quelli", "quelle",
    # Indefiniti e quantificatori
    "tutto", "tutti", "tutte", "ogni",
    # Fillers (anche in stopwords per keyword extraction)
    "però", "allora", "quindi", "cioè", "tipo", "ecco",
    # Parole spurie frequenti nei transcript
    "veste",
})

FILLER_PATTERN = re.compile(
    r'(?<!\w)(uhm|ah+|eh+|mh+|tipo|cioè|quindi|allora|ecco|'
    r'praticamente|sostanzialmente|diciamo)'
    r'(?=\s*[,.]|\s+(?:e|ma|però|che|il|la|lo|i|gli|le|un|una)\s)'
    r'|\b(no\?|vero\?|capito\?)\b',
    re.IGNORECASE
)
CONSEC_WORD_PATTERN = re.compile(r'\b(\w+)\s+\1\b', re.IGNORECASE)
MULTI_SPACE_PATTERN = re.compile(r'\s{2,}')


def _ts_to_secs(ts_str):
    """Convert 'HH:MM:SS' or 'HH:MM:SS.mmm' to float seconds."""
    try:
        parts = re.split(r'[:.]', ts_str)
        h, m, s = int(parts[0]), int(parts[1]), int(parts[2])
        ms = int(parts[3]) if len(parts) > 3 else 0
        return h * 3600 + m * 60 + s + ms / 1000.0
    except (ValueError, IndexError):
        return 0.0


def deduplicate_sentences(text):
    sentences = text.split(". ")
    seen = []
    for s in sentences:
        if s.strip() not in [x.strip() for x in seen]:
            seen.append(s)
    return ". ".join(seen)


def clean_text(raw):
    """Remove Italian fillers (context-aware), collapse duplicate words, deduplicate sentences."""
    if not raw:
        return ""
    text = FILLER_PATTERN.sub("", raw)
    prev = None
    while prev != text:
        prev = text
        text = CONSEC_WORD_PATTERN.sub(r'\1', text)
    text = MULTI_SPACE_PATTERN.sub(" ", text).strip()
    return deduplicate_sentences(text)


def extract_keywords(text, top_n=5):
    """Top-N content words by frequency, Italian stopwords excluded.
    Fallback: if fewer than 3 results, pad with longest words (len > 4)."""
    if not text:
        return []
    words = re.findall(r'\b\w{3,}\b', text.lower())
    filtered = [w for w in words if w not in ITALIAN_STOPWORDS]
    result = [w for w, _ in Counter(filtered).most_common(top_n)]
    if len(result) < 3:
        long_words = sorted(set(w for w in filtered if len(w) > 4), key=lambda w: -len(w))
        for w in long_words:
            if w not in result:
                result.append(w)
            if len(result) >= top_n:
                break
    return result[:top_n]


# ── Read all sources ──────────────────────────────────────────────────────────
def read_json(path):
    if os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError, UnicodeDecodeError) as e:
            print(f"    WARNING: could not read {path}: {e}", file=sys.stderr)
            return {}
    return {}

def read_text(path):
    if os.path.exists(path):
        for enc in ("utf-8-sig", "utf-8", "cp1252", "latin-1"):
            try:
                with open(path, encoding=enc) as f:
                    return f.read().strip()
            except UnicodeDecodeError:
                continue
    return ""

metadata             = read_json(os.path.join(args.work_dir, "metadata.json"))
if args.model:
    metadata["whisper_model"] = args.model
manifest             = read_json(os.path.join(args.work_dir, "manifest.json"))
clusters             = read_json(os.path.join(args.work_dir, "clusters.json"))
transcript_raw       = read_text(os.path.join(args.work_dir, "transcript.txt"))
_vt_auto_raw         = read_json(os.path.join(args.work_dir, "visual_timeline_auto.json"))
visual_timeline_auto = _vt_auto_raw if isinstance(_vt_auto_raw, list) else []

_char_app_raw = read_json(os.path.join(args.work_dir, "character_appearances.json"))
character_appearances = _char_app_raw if isinstance(_char_app_raw, dict) else {}

_raw_nodes = read_json(os.path.join(args.work_dir, "intermediate_nodes.json"))
intermediate_nodes = _raw_nodes if isinstance(_raw_nodes, list) else []

# Load enriched transcript_segments (with Whisper confidence scores) written by
# process_video.py. Falls back to parsing transcript.txt when the JSON file is
# absent (backward compatibility with runs predating confidence scoring).
_raw_segs = read_json(os.path.join(args.work_dir, "transcript_segments.json"))
transcript_segments = _raw_segs if isinstance(_raw_segs, list) else []

if not transcript_segments and transcript_raw and transcript_raw not in ("NO_AUDIO", "") \
        and not transcript_raw.startswith("TRANSCRIPTION_ERROR"):
    for line in transcript_raw.splitlines():
        line = line.strip()
        if line.startswith("[") and "]" in line:
            bracket_end = line.index("]")
            ts = line[1:bracket_end]
            # Strip ⚠️ low-confidence marker that process_video.py may have appended.
            text = re.sub(r"\s*⚠️\s*$", "", line[bracket_end + 1:]).strip()
            transcript_segments.append({
                "timestamp": ts,
                "text": text,
                "avg_logprob": None,
                "no_speech_prob": None,
                "confidence": None,
                "low_confidence": None,
            })

for seg in transcript_segments:
    if "source" not in seg:
        seg["source"] = "audio"

visual_timeline  = json.loads(args.visual_timeline)  if args.visual_timeline  else []
character_names  = json.loads(args.character_names)  if args.character_names  else {}
key_observations = json.loads(args.key_observations) if args.key_observations else []

# Merge auto-generated timeline (from process_video.py Vision batch) into CLI-provided one.
# Auto entries fill only gaps not already covered by a CLI entry.
_cli_ts_set = {e.get("timestamp", "")[:8] for e in visual_timeline}
for _entry in visual_timeline_auto:
    if _entry.get("timestamp", "")[:8] not in _cli_ts_set:
        visual_timeline.append(_entry)

for _entry in visual_timeline:
    if "source" not in _entry:
        _entry["source"] = "vision"

# Bridge visual_timeline → intermediate_nodes.visual_delta.
# For each timeline entry find the temporally closest node and populate its
# visual_delta if it is still unresolved ("analisi frame", None, or "vision_error").
if visual_timeline and intermediate_nodes:
    for _vt in visual_timeline:
        _vt_secs = _ts_to_secs(_vt.get("timestamp", "00:00:00"))
        _desc = _vt.get("description", "").strip()
        if not _desc:
            continue
        _closest = min(
            intermediate_nodes,
            key=lambda n: abs(_ts_to_secs(n.get("anchor_ts", "00:00:00.000")) - _vt_secs),
        )
        _dist = abs(_ts_to_secs(_closest.get("anchor_ts", "00:00:00.000")) - _vt_secs)
        if _dist <= 5.0 and _closest.get("visual_delta") in (None, "analisi frame", "vision_error"):
            _closest["visual_delta"]    = _desc
            _closest["visual_delta_ts"] = _vt.get("timestamp", "")  # exact frame timestamp

char_list = []
if character_names:
    # first_seen / appearances are not tracked per-character in the current pipeline:
    # --character-names is a flat id→name map; Vision does not tag individual frames
    # with character IDs. Both fields are set to "n/d" to make the gap explicit in
    # the report rather than leaving an invisible missing key.
    if not character_appearances:
        print("   NOTE: per-frame character tracking not available — "
              "first_seen/appearances set to n/d", flush=True)
    else:
        print(f"   Character appearances loaded: {len(character_appearances)} "
              f"character(s) tracked", flush=True)
    for cid_str, name in sorted(character_names.items(),
                                 key=lambda x: int(x[0]) if x[0].isdigit() else 0):
        _app_data = character_appearances.get(cid_str, {})
        _raw_app  = _app_data.get("appearances", "n/d")
        # detect_characters.py writes appearances as a list; normalise to a
        # human-readable string so PDF/MD renderers don't get Python list repr.
        if isinstance(_raw_app, list):
            _raw_app = (f"{len(_raw_app)} ({', '.join(str(t) for t in _raw_app)})"
                        if _raw_app else "n/d")
        char_list.append({
            "character_id": int(cid_str) if cid_str.isdigit() else cid_str,
            "name": name,
            "first_seen":  _app_data.get("first_seen",  "n/d"),
            "appearances": _raw_app,
        })

# ── Process intermediate_nodes ────────────────────────────────────────────────
nodes_before = len(intermediate_nodes)
chars_raw_total = sum(len(n.get("text_raw") or "") for n in intermediate_nodes)

# A) text_raw → text_clean
for node in intermediate_nodes:
    node["text_clean"] = clean_text(node.get("text_raw") or "")

# B) Segment merging — single forward pass
#    Priority 1: near-duplicate removal (Jaccard ≥ 0.85 → keep first, discard second)
#    Priority 2: standard merge (visual_delta None, gap < 1500 ms, combined < 800 chars)

def is_near_duplicate(text_a, text_b, threshold=0.85):
    words_a = set(text_a.lower().split())
    words_b = set(text_b.lower().split())
    if not words_a or not words_b:
        return False
    overlap = len(words_a & words_b) / len(words_a | words_b)
    return overlap >= threshold


merged_nodes = []
merges = 0
dedup_merges = 0
i = 0
while i < len(intermediate_nodes):
    current = intermediate_nodes[i]
    if i + 1 < len(intermediate_nodes):
        nxt = intermediate_nodes[i + 1]
        raw_curr   = current.get("text_raw") or ""
        raw_nxt    = nxt.get("text_raw") or ""
        clean_curr = current.get("text_clean") or ""
        clean_nxt  = nxt.get("text_clean") or ""
        curr_win = current.get("window_ms") or [0, 0]
        nxt_win  = nxt.get("window_ms") or [0, 0]
        gap = nxt_win[0] - curr_win[1]

        if is_near_duplicate(raw_curr, raw_nxt):
            # Near-duplicate: keep first node's text but prefer the richer visual_delta
            best_delta = (current.get("visual_delta")
                          if current.get("visual_delta") not in (None, "analisi frame", "vision_error")
                          else nxt.get("visual_delta"))
            merged_nodes.append({
                **current,
                "window_ms": [curr_win[0], nxt_win[1]],
                "visual_delta": best_delta,
            })
            i += 2
            merges += 1
            dedup_merges += 1
            continue

        if (nxt.get("visual_delta") is None
                and gap < 1500
                and len(clean_curr) + len(clean_nxt) < 800):
            merged_nodes.append({
                **current,
                "window_ms": [curr_win[0], nxt_win[1]],
                "text_raw":   (raw_curr + " " + raw_nxt).strip(),
                "text_clean": (clean_curr + " " + clean_nxt).strip(),
            })
            i += 2
            merges += 1
            continue

    merged_nodes.append(current)
    i += 1
intermediate_nodes = merged_nodes
nodes_after = len(intermediate_nodes)

# F) Sequential renumbering — eliminates gaps (n_0000, n_0002…) left by merge
for idx, node in enumerate(intermediate_nodes):
    node["node_id"] = f"n_{idx:04d}"

for node in intermediate_nodes:
    if "source" not in node:
        node["source"] = "audio"

# C) Keywords  D) Embedding hint
chars_clean_total = 0
for node in intermediate_nodes:
    tc = node.get("text_clean") or ""
    node["keywords"] = extract_keywords(tc)
    kw_str = " ".join(node["keywords"])
    node["embedding_hint"] = (kw_str + ". " if kw_str else "") + tc[:200]
    chars_clean_total += len(tc)

# E) Global index — 10-node clusters
CLUSTER_SIZE = 10
global_index = []
for ci in range(0, len(intermediate_nodes), CLUSTER_SIZE):
    group = intermediate_nodes[ci:ci + CLUSTER_SIZE]
    global_index.append({
        "cluster_id": f"c_{ci // CLUSTER_SIZE:02d}",
        "ts_range":   [group[0]["anchor_ts"], group[-1]["anchor_ts"]],
        "summary":    (group[0].get("text_clean") or "")[:100],
        "node_ids":   [n["node_id"] for n in group],
    })

def _build_language_note(meta):
    lang     = meta.get("language_detected", "unknown")
    forced   = meta.get("language_forced")
    prob     = meta.get("language_detection_prob")
    if forced:
        return f"impostata manualmente: {lang}"
    if prob is not None:
        pct = round(prob * 100)
        if pct < 60:
            return f"rilevata automaticamente: {lang} ({pct}% — bassa confidenza, verificare)"
        return f"rilevata automaticamente: {lang} ({pct}%)"
    return f"rilevata automaticamente: {lang}"

# ── Overwrite intermediate_nodes.json with enriched nodes ─────────────────────
nodes_path = os.path.join(args.work_dir, "intermediate_nodes.json")
with open(nodes_path, "w", encoding="utf-8") as f:
    json.dump(intermediate_nodes, f, indent=2, ensure_ascii=False)

# ── Assemble final report ─────────────────────────────────────────────────────
report = {
    "schema_version": "2.0",
    "generated_by": "video-analyzer skill",
    "disclaimers": {
        "audio": "Testo trascritto da Whisper: verificabile riascoltando il video originale.",
        "vision": "Descrizioni visive generate da Claude Vision analizzando singoli fotogrammi: inferenza automatica, può contenere errori di interpretazione.",
    },
    "metadata": metadata,
    "global_index": global_index,
    "characters": {
        "count": len(char_list),
        "count_source": "claude_vision" if character_names else "not_provided",
        "list": char_list,
    },
    "rag_timeline": intermediate_nodes,
    "audio": {
        "has_audio": bool(transcript_segments) or (
            bool(transcript_raw)
            and transcript_raw not in ("NO_AUDIO", "")
            and not transcript_raw.startswith("TRANSCRIPTION_ERROR")
        ),
        "language_detected":       metadata.get("language_detected", "unknown"),
        "language_forced":         metadata.get("language_forced"),
        "language_detection_prob": metadata.get("language_detection_prob"),
        "language_note":           _build_language_note(metadata),
        "transcript_segments": transcript_segments,
    },
    "visual_timeline": visual_timeline,
    "summary": args.summary,
    "key_observations": key_observations,
}

with open(args.output, "w", encoding="utf-8") as f:
    json.dump(report, f, indent=2, ensure_ascii=False)

# ── Stats ─────────────────────────────────────────────────────────────────────
pct = round((1 - chars_clean_total / chars_raw_total) * 100, 1) if chars_raw_total else 0
print(f"✅ JSON report written to {args.output}")
print(f"   Schema version     : {report['schema_version']}")
print(f"   Nodes before merge : {nodes_before}")
print(f"   Nodes after merge  : {nodes_after}  ({merges} merged, {dedup_merges} near-dup removed)")
print(f"   text_raw chars     : {chars_raw_total}")
print(f"   text_clean chars   : {chars_clean_total}  ({pct}% reduction)")
print(f"   Global index       : {len(global_index)} cluster(s)")
print(f"   Characters         : {report['characters']['count']} ({report['characters']['count_source']})")
print(f"   Transcript segments: {len(transcript_segments)}")
print(f"   Visual timeline    : {len(visual_timeline)} entries")

# ── Generate PDF (unified entry point) ────────────────────────────────────────
try:
    _scripts_dir = os.path.dirname(os.path.abspath(__file__))
    if _scripts_dir not in sys.path:
        sys.path.insert(0, _scripts_dir)
    from build_pdf_report import generate_pdf
    _frames_dir = os.path.join(args.work_dir, "frames")
    _out_dir    = os.path.dirname(os.path.abspath(args.output)) or args.work_dir
    generate_pdf(args.output, _frames_dir, _out_dir)
except Exception as _pdf_err:
    print(f"   PDF generation skipped: {_pdf_err}", flush=True)
