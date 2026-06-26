#!/usr/bin/env python3
"""
process_video.py — Video pre-processing for the video-analyzer skill.

Usage:
    python3 process_video.py <video_path> [--max-frames 30] [--output-dir /tmp/video_work]

Outputs (inside --output-dir):
    frames/                   — JPEG frames (scene_%04d.jpg, one per detected scene change)
    audio.wav                 — extracted mono 16kHz audio
    transcript.txt            — Whisper transcription (or "NO_AUDIO" if silent/no audio)
    metadata.json             — ffprobe metadata as JSON
    manifest.json             — list of frame paths + timestamps
    intermediate_nodes.json   — event-driven nodes: Whisper segments × scene change proximity,
                                with visual_delta filled by batch Vision if ANTHROPIC_API_KEY is set
"""

import argparse
import json
import os
import re
import subprocess
import sys

# Ensure stdout/stderr can render non-ASCII output on Windows (cp1252).
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# ── Args ─────────────────────────────────────────────────────────────────────
parser = argparse.ArgumentParser()
parser.add_argument("video", help="Path to the video file")
parser.add_argument("--fps", type=float, default=0.5,
                    help="Deprecated: scene detection replaces fixed-fps extraction. "
                         "Kept for backward compatibility but not used for frame sampling.")
parser.add_argument("--max-frames", type=int, default=30,
                    help="Hard cap on scene-change frames extracted (default 30)")
parser.add_argument("--output-dir", default="/tmp/video_work",
                    help="Working directory for extracted assets")
parser.add_argument("--model", default="large-v3-turbo",
                    help="Whisper model: tiny / base / small / medium / large / large-v3-turbo (default large-v3-turbo)")
parser.add_argument("--task", default="transcribe", choices=["transcribe", "translate"],
                    help="Task to perform: transcribe or translate to English (default transcribe)")
parser.add_argument("--language", default=None,
                    help="Force audio language for Whisper (e.g. 'it', 'en'). "
                         "Leave unset to let Whisper auto-detect (default).")
parser.add_argument("--vision-model", default="claude-haiku-4-5-20251001",
                    help="Claude model used for Vision batch (default claude-haiku-4-5-20251001)")
args = parser.parse_args()

VIDEO = args.video
OUTDIR = args.output_dir
FRAMES_DIR = os.path.join(OUTDIR, "frames")
os.makedirs(FRAMES_DIR, exist_ok=True)

def run(cmd, **kw):
    return subprocess.run(cmd, capture_output=True, text=True, **kw)

def _parse_rate(rate_str):
    """Parse an ffprobe rate string like '30/1' or '30000/1001' safely."""
    try:
        num, den = rate_str.split("/")
        den = float(den)
        return float(num) / den if den else 0.0
    except (ValueError, AttributeError):
        return 0.0

def format_ts(seconds):
    """Format float seconds as HH:MM:SS.mmm"""
    h = int(seconds) // 3600
    mn = (int(seconds) % 3600) // 60
    s_int = int(seconds) % 60
    ms = int(round((seconds - int(seconds)) * 1000))
    return f"{h:02d}:{mn:02d}:{s_int:02d}.{ms:03d}"

def ts_to_seconds(ts_str):
    """Parse HH:MM:SS.mmm → float seconds"""
    parts = ts_str.replace(".", ":").split(":")
    h, mn, s, ms = int(parts[0]), int(parts[1]), int(parts[2]), int(parts[3])
    return h * 3600 + mn * 60 + s + ms / 1000.0

def find_closest_frame(anchor_secs, manifest_list):
    """Return the manifest entry whose timestamp is closest to anchor_secs."""
    if not manifest_list:
        return None
    return min(manifest_list, key=lambda f: abs(f["timestamp_seconds"] - anchor_secs))

# ── 1. Metadata ───────────────────────────────────────────────────────────────
print("[1/5] Extracting metadata …", flush=True)
meta = run([
    "ffprobe", "-v", "quiet", "-print_format", "json", "-show_format",
    "-show_streams", VIDEO
])
metadata = json.loads(meta.stdout) if meta.returncode == 0 else {}

fmt = metadata.get("format", {})
streams = metadata.get("streams", [])
video_stream = next((s for s in streams if s.get("codec_type") == "video"), {})
audio_stream = next((s for s in streams if s.get("codec_type") == "audio"), {})

duration_s = float(fmt.get("duration", 0))
dh, drem = divmod(int(duration_s), 3600)
dm, ds = divmod(drem, 60)
duration_fmt = f"{dh:02d}:{dm:02d}:{ds:02d}"

max_frames = args.max_frames

summary_meta = {
    "filename": os.path.basename(VIDEO),
    "duration_seconds": round(duration_s, 2),
    "duration_formatted": duration_fmt,
    "size_mb": round(int(fmt.get("size", 0)) / 1024**2, 2),
    "video_codec": video_stream.get("codec_name", "unknown"),
    "width": video_stream.get("width"),
    "height": video_stream.get("height"),
    "fps_original": _parse_rate(video_stream.get("r_frame_rate", "0/1")),
    "audio_codec": audio_stream.get("codec_name", "none"),
    "audio_sample_rate": audio_stream.get("sample_rate"),
    "bitrate_kbps": round(int(fmt.get("bit_rate", 0)) / 1000, 1),
    "whisper_model": args.model,
    "vision_model": args.vision_model,
}
with open(os.path.join(OUTDIR, "metadata.json"), "w") as f:
    json.dump(summary_meta, f, indent=2)
print(f"    Duration: {duration_fmt}  |  {summary_meta['width']}x{summary_meta['height']}  |  {summary_meta['video_codec']}", flush=True)

# ── 2. Scene detection + frame extraction ─────────────────────────────────────
# Replaces fixed-fps sampling: ffmpeg selects frames only at visual scene changes
# (score > 0.4). showinfo logs pts_time for each selected frame → scene_timestamps[].
print(f"[2/5] Detecting scene changes (threshold 0.4) and extracting frames …", flush=True)
scene_pattern = os.path.join(FRAMES_DIR, "scene_%04d.jpg")
scene_timestamps = []

scene_result = run([
    "ffmpeg", "-y", "-i", VIDEO,
    "-vf", (
        "select='gt(scene,0.4)',showinfo,"
        "scale='min(1568,iw)':'min(1568,ih)':force_original_aspect_ratio=decrease"
    ),
    "-vsync", "vfr",
    "-q:v", "3",
    "-frames:v", str(max_frames),
    scene_pattern
])

# showinfo writes to stderr; parse pts_time from each matching line
for line in scene_result.stderr.splitlines():
    if "showinfo" in line or "Parsed_showinfo" in line:
        ts_match = re.search(r"pts_time:([\d.]+)", line)
        if ts_match:
            scene_timestamps.append(float(ts_match.group(1)))

frames = sorted(f for f in os.listdir(FRAMES_DIR) if f.endswith(".jpg"))

# Fallback: if no scene changes detected, extract a single keyframe at t=0
if not frames:
    print("    No scene changes above threshold — extracting first keyframe as fallback …", flush=True)
    fallback_path = os.path.join(FRAMES_DIR, "scene_0001.jpg")
    run([
        "ffmpeg", "-y", "-i", VIDEO,
        "-vf", "scale='min(1568,iw)':'min(1568,ih)':force_original_aspect_ratio=decrease",
        "-q:v", "3", "-frames:v", "1",
        fallback_path
    ])
    frames = sorted(f for f in os.listdir(FRAMES_DIR) if f.endswith(".jpg"))
    if frames:
        scene_timestamps = [0.0]

if len(scene_timestamps) < len(frames):
    print(f"    WARNING: {len(frames)} frames but only {len(scene_timestamps)} scene timestamps — "
          f"{len(frames) - len(scene_timestamps)} frame(s) will use ts=0.0", flush=True)

manifest = []
for i, fname in enumerate(frames):
    ts = scene_timestamps[i] if i < len(scene_timestamps) else 0.0
    fh, frem = divmod(int(ts), 3600)
    fm, fs = divmod(frem, 60)
    manifest.append({
        "path": os.path.join(FRAMES_DIR, fname),
        "timestamp_seconds": round(ts, 2),
        "timestamp_formatted": f"{fh:02d}:{fm:02d}:{fs:02d}",
    })
with open(os.path.join(OUTDIR, "manifest.json"), "w") as f:
    json.dump(manifest, f, indent=2)
print(f"    Scene changes: {len(scene_timestamps)}  |  Frames extracted: {len(frames)}", flush=True)

# ── 3. Audio ──────────────────────────────────────────────────────────────────
print("[3/5] Extracting audio …", flush=True)
AUDIO_PATH = os.path.join(OUTDIR, "audio.wav")
audio_res = run([
    "ffmpeg", "-y", "-i", VIDEO,
    "-vn", "-acodec", "pcm_s16le",
    "-ar", "16000", "-ac", "1",
    AUDIO_PATH
])
has_audio = audio_res.returncode == 0 and os.path.exists(AUDIO_PATH) and os.path.getsize(AUDIO_PATH) > 1000

# ── 4. Transcription / Translation ──────────────────────────────────────────
TRANSCRIPT_PATH = os.path.join(OUTDIR, "transcript.txt")
segments = []

if has_audio:
    model_name = args.model.lower().strip()
    if model_name == "turbo":
        model_name = "large-v3-turbo"

    print(f"[4/5] Processing audio with Whisper ({model_name}) | Task: {args.task} …", flush=True)
    try:
        import whisper
        model = whisper.load_model(model_name)
        result = model.transcribe(AUDIO_PATH, task=args.task, fp16=False, verbose=False,
                                  language=args.language, beam_size=5)
        transcript = result.get("text", "").strip()
        segments = result.get("segments", [])
        language_detected = result.get("language", "it")
        summary_meta["language_detected"] = language_detected
        summary_meta["whisper_model"] = model_name
        with open(os.path.join(OUTDIR, "metadata.json"), "w", encoding="utf-8") as f:
            json.dump(summary_meta, f, indent=2)

        lines = []
        for seg in segments:
            t0 = int(seg["start"])
            sh, srem = divmod(t0, 3600)
            smn, ss = divmod(srem, 60)
            lines.append(f"[{sh:02d}:{smn:02d}:{ss:02d}] {seg['text'].strip()}")

        with open(TRANSCRIPT_PATH, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) if lines else transcript)
        print(f"    Processing done ({len(transcript)} chars, {len(segments)} segments)", flush=True)
    except Exception as e:
        print(f"    Whisper error: {e}", flush=True)
        with open(TRANSCRIPT_PATH, "w") as f:
            f.write("TRANSCRIPTION_ERROR: " + str(e))
else:
    print("[4/5] No audio track found — skipping transcription", flush=True)
    with open(TRANSCRIPT_PATH, "w") as f:
        f.write("NO_AUDIO")

# ── 5. Build intermediate_nodes.json + batch Vision ───────────────────────────
# Whisper segments are the master clock; scene_timestamps gate Vision calls.
# visual_delta = "analisi frame" → node is near a scene change, Vision needed.
# visual_delta = None            → static scene, inherit previous description.
# Vision batch resolves "analisi frame" flags into actual descriptions.
print("[5/5] Building intermediate_nodes.json …", flush=True)
intermediate_nodes = []

for i, seg in enumerate(segments):
    seg_start = float(seg["start"])

    if scene_timestamps:
        min_dist = min(abs(seg_start - st) for st in scene_timestamps)
        visual_delta = "analisi frame" if min_dist <= 2.0 else None
    else:
        visual_delta = None

    intermediate_nodes.append({
        "node_id": f"n_{i:04d}",
        "anchor_ts": format_ts(seg_start),
        "window_ms": [int(seg["start"] * 1000), int(seg["end"] * 1000)],
        "text_raw": seg["text"].strip(),
        "text_clean": None,
        "visual_delta": visual_delta,
        "keywords": [],
        "embedding_hint": None,
    })

vision_nodes = [(i, n) for i, n in enumerate(intermediate_nodes) if n["visual_delta"] == "analisi frame"]
print(f"    Nodes: {len(intermediate_nodes)}  |  Vision calls flagged: {len(vision_nodes)}", flush=True)

# ── Vision batch ───────────────────────────────────────────────────────────────
# Groups up to 20 flagged frames per API call. Skipped gracefully if the
# anthropic package is missing or ANTHROPIC_API_KEY is not set.
visual_timeline_auto = []
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
        print("    ANTHROPIC_API_KEY not set — skipping Vision batch", flush=True)
except ImportError:
    print("    anthropic package not installed — skipping Vision batch", flush=True)

BATCH_SIZE = 20
VISION_PROMPT = (
    "Per ogni immagine fornita in ordine, descrivi in massimo 2 frasi "
    "concise cosa vedi nella scena. Sii specifico su persone, oggetti, ambientazione.\n"
    "Formato risposta obbligatorio: IMAGE_1: descrizione | IMAGE_2: descrizione | ..."
)

if _vision_ready and vision_nodes:
    num_batches = (len(vision_nodes) + BATCH_SIZE - 1) // BATCH_SIZE
    print(f"    Running Vision batch ({len(vision_nodes)} frame(s) in {num_batches} batch(es)) …", flush=True)

    for batch_num, batch_start in enumerate(range(0, len(vision_nodes), BATCH_SIZE)):
        batch = vision_nodes[batch_start:batch_start + BATCH_SIZE]

        # Map each vision node to its closest extracted frame
        valid_items = []  # (node_idx, frame_path)
        for node_idx, node in batch:
            anchor_secs = ts_to_seconds(node["anchor_ts"])
            closest = find_closest_frame(anchor_secs, manifest)
            if closest and os.path.exists(closest["path"]):
                valid_items.append((node_idx, closest["path"]))

        if not valid_items:
            continue

        # Build API message: images first, text prompt last
        content = []
        for _, frame_path in valid_items:
            with open(frame_path, "rb") as fimg:
                b64_data = _b64.standard_b64encode(fimg.read()).decode("utf-8")
            content.append({
                "type": "image",
                "source": {"type": "base64", "media_type": "image/jpeg", "data": b64_data},
            })
        content.append({"type": "text", "text": VISION_PROMPT})

        try:
            msg = _anthropic_client.messages.create(
                model=args.vision_model,
                max_tokens=512,
                messages=[{"role": "user", "content": content}],
            )
            response_text = msg.content[0].text

            # Parse "IMAGE_N: description | IMAGE_N+1: description | ..."
            descriptions = {}
            for part in response_text.split("|"):
                part = part.strip()
                m_parse = re.search(r"IMAGE_(\d+):\s*(.+)", part, re.IGNORECASE)
                if m_parse:
                    idx = int(m_parse.group(1)) - 1  # 0-indexed
                    if idx >= 0:
                        descriptions[idx] = m_parse.group(2).strip()

            for batch_idx, (node_idx, _) in enumerate(valid_items):
                desc = descriptions.get(batch_idx)
                if desc:
                    intermediate_nodes[node_idx]["visual_delta"] = desc
                    visual_timeline_auto.append({
                        "timestamp": intermediate_nodes[node_idx]["anchor_ts"][:8],
                        "description": desc,
                    })

            resolved = sum(1 for k in descriptions if k < len(valid_items))
            print(f"    Batch {batch_num + 1}/{num_batches}: {len(valid_items)} frame(s) → {resolved} description(s)", flush=True)

        except Exception as e:
            print(f"    Vision batch {batch_num + 1} failed: {e}", flush=True)
            for node_idx, _ in valid_items:
                if intermediate_nodes[node_idx]["visual_delta"] == "analisi frame":
                    intermediate_nodes[node_idx]["visual_delta"] = "vision_error"

NODES_PATH = os.path.join(OUTDIR, "intermediate_nodes.json")
with open(NODES_PATH, "w", encoding="utf-8") as f:
    json.dump(intermediate_nodes, f, indent=2, ensure_ascii=False)

if visual_timeline_auto:
    vt_auto_path = os.path.join(OUTDIR, "visual_timeline_auto.json")
    with open(vt_auto_path, "w", encoding="utf-8") as f:
        json.dump(visual_timeline_auto, f, indent=2, ensure_ascii=False)
    print(f"    Saved visual_timeline_auto: {len(visual_timeline_auto)} entries", flush=True)

still_flagged = sum(1 for n in intermediate_nodes if n["visual_delta"] == "analisi frame")
resolved_vision = len(vision_nodes) - still_flagged
print(f"    Saved: {len(intermediate_nodes)} nodes  |  Vision resolved: {resolved_vision}/{len(vision_nodes)}", flush=True)

# ── Done ──────────────────────────────────────────────────────────────────────
print("\n✅ Pre-processing complete!", flush=True)
print(f"   Output dir        : {OUTDIR}")
print(f"   Frames            : {len(frames)}  (scene-change driven)")
print(f"   Scene timestamps  : {scene_timestamps}")
print(f"   Transcript        : {TRANSCRIPT_PATH}")
print(f"   Intermediate nodes: {NODES_PATH}")
print(f"   Metadata          : {os.path.join(OUTDIR, 'metadata.json')}")
