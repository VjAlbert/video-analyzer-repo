#!/usr/bin/env python3
"""
cluster_frames.py — Visual scene clustering for the video-analyzer skill.

Groups extracted frames by color/composition similarity (HSV histogram) to
identify visually distinct scene groups and select representative frames.
This is a frame-selection aid, NOT a character detector or face recognizer.

Usage:
    python3 cluster_frames.py --frames-dir /tmp/video_work/frames \
                               --output /tmp/video_work/clusters.json \
                               --manifest /tmp/video_work/manifest.json

Strategy:
  1. For each frame: extract HSV histogram from the central region
  2. Greedy clustering by histogram correlation — frames above threshold
     land in the same visual cluster
  3. Pick the most representative frame per cluster
  4. Output clusters.json with: visual_cluster_count, clusters,
     representative_frame paths (use these to pick frames for Claude Vision)
"""

import argparse
import json
import os
import sys

# Ensure stdout/stderr can render non-ASCII output on Windows (cp1252).
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

import cv2
import numpy as np

parser = argparse.ArgumentParser()
parser.add_argument("--frames-dir", required=True)
parser.add_argument("--output", required=True)
parser.add_argument("--manifest", required=True)
parser.add_argument("--similarity-threshold", type=float, default=0.72,
                    help="Histogram correlation threshold (0-1). Higher = stricter grouping.")
args = parser.parse_args()

# ── Load manifest ─────────────────────────────────────────────────────────────
with open(args.manifest) as f:
    manifest = json.load(f)

frame_paths = [e["path"] for e in manifest if os.path.exists(e["path"])]
if not frame_paths:
    print("No frames found.", file=sys.stderr)
    sys.exit(1)

# ── Compute HSV histogram fingerprint per frame ───────────────────────────────
def frame_fingerprint(path):
    img = cv2.imread(path)
    if img is None:
        return None
    h, w = img.shape[:2]
    roi = img[0:int(h * 0.70), int(w * 0.20):int(w * 0.80)]
    hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
    # 3-channel histogram: H(18 bins), S(8 bins), V(8 bins)
    hist = cv2.calcHist([hsv], [0, 1, 2], None, [18, 8, 8],
                        [0, 180, 0, 256, 0, 256])
    cv2.normalize(hist, hist)
    return hist.flatten()

print("Computing frame fingerprints…", flush=True)
fingerprints = {}
for p in frame_paths:
    fp = frame_fingerprint(p)
    if fp is not None:
        fingerprints[p] = fp

# ── Greedy clustering by histogram correlation ────────────────────────────────
clusters = []  # list of {representative, members: [paths], timestamps: [...]}

manifest_by_path = {e["path"]: e for e in manifest}

def hist_corr(a, b):
    h1 = a.reshape(18, 8, 8).astype(np.float32)
    h2 = b.reshape(18, 8, 8).astype(np.float32)
    return cv2.compareHist(h1, h2, cv2.HISTCMP_CORREL)

print("Clustering frames by visual similarity…", flush=True)
threshold = args.similarity_threshold

for path in frame_paths:
    if path not in fingerprints:
        continue
    fp = fingerprints[path]
    matched = False
    for cluster in clusters:
        rep_fp = fingerprints[cluster["representative"]]
        score = hist_corr(fp, rep_fp)
        if score >= threshold:
            cluster["members"].append(path)
            cluster["timestamps"].append(
                manifest_by_path.get(path, {}).get("timestamp_formatted", "?"))
            matched = True
            break
    if not matched:
        clusters.append({
            "cluster_id": len(clusters) + 1,
            "representative": path,
            "representative_timestamp": manifest_by_path.get(path, {}).get("timestamp_formatted", "?"),
            "members": [path],
            "timestamps": [manifest_by_path.get(path, {}).get("timestamp_formatted", "?")],
        })

# Sort clusters by number of frames (largest first)
clusters.sort(key=lambda c: len(c["members"]), reverse=True)
for i, c in enumerate(clusters):
    c["cluster_id"] = i + 1

# ── Output ────────────────────────────────────────────────────────────────────
result = {
    "visual_cluster_count": len(clusters),
    "note": "Clusters are grouped by color/composition similarity — not by identity. "
            "Use representative_frame paths to pick frames for Claude Vision.",
    "clusters": [
        {
            "cluster_id": c["cluster_id"],
            "frame_count": len(c["members"]),
            "first_seen": c["timestamps"][0] if c["timestamps"] else "?",
            "last_seen": c["timestamps"][-1] if c["timestamps"] else "?",
            "representative_frame": c["representative"],
            "representative_timestamp": c["representative_timestamp"],
            "all_timestamps": c["timestamps"],
        }
        for c in clusters
    ]
}

with open(args.output, "w") as f:
    json.dump(result, f, indent=2)

print(f"\n✅ Found {len(clusters)} visual cluster(s) (color/composition grouping).", flush=True)
for c in clusters:
    print(f"   Cluster {c['cluster_id']}: {len(c['members'])} frames "
          f"(first: {c['timestamps'][0] if c['timestamps'] else '?'})", flush=True)
print("\nNote: cluster count is a scene-grouping estimate, not a character count.", flush=True)
