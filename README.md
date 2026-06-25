# video-analyzer (Claude Skill)

> Converts video files into structured Markdown and JSON reports using local preprocessing and Claude Vision. 

This Claude Skill acts as a bridge for LLM environments (such as Claude Projects) that do not natively support direct video uploads. It extracts audio transcripts, identifies key visual transitions, groups frames by color composition, and structures this data into AI-friendly and human-readable formats.

---

## Architectural Overview

The skill follows a decoupled multi-stage pipeline designed to minimize API token usage while capturing key details:

```
                  ┌──────────────────────────────┐
                  │         Input Video          │
                  └──────────────┬───────────────┘
                                 │
                     [ process_video.py ]
                                 │
       ┌─────────────────────────┴────────────────────────┐
       ▼                                                  ▼
┌──────────────┐                                   ┌──────────────┐
│  Audio Track │                                   │ Video Frames │
└──────┬───────┘                                   └──────┬───────┘
       │ [Whisper Turbo]                                  │ (Max 1568px long edge)
       ▼                                                  ▼
┌──────────────┐                                   ┌──────────────┐
│  Transcript  │                                   │   Manifest   │
└──────┬───────┘                                   └──────┬───────┘
       │                                                  │
       │                                        [ cluster_frames.py ]
       │                                                  │
       │                                                  ▼
       │                                           ┌──────────────┐
       │                                           │ Visual Scene │
       │                                           │  Clusters    │
       │                                           └──────┬───────┘
       │                                                  │
       │             ┌────────────────────────┐           │ (Selected Frames)
       │             │   Claude Vision Pass   │◄──────────┘
       │             │ (Character Count & ID) │
       │             └───────────┬────────────┘
       │                         │
       ▼                         ▼
   ┌───────────────────────────────────┐
   │       [ build_json_report.py ]    │
   └─────────────────┬─────────────────┘
                     │
                     ▼
       ┌─────────────────────────┴────────────────────────┐
       ▼                                                  ▼
┌──────────────┐                                   ┌──────────────┐
│  JSON Report │                                   │   Markdown   │
│  (Structured)│                                   │   Summary    │
└──────────────┘                                   └──────────────┘
```

---

## Technical Specifications & Pipeline Stages

### Stage 1: Extraction & Preprocessing (`process_video.py`)
The pipeline begins by isolating the audio track and extracting downscaled video frames.
* **Frame Extraction**: Frames are extracted at a configurable rate (default: `0.5` fps, or one frame every 2 seconds) and capped at a maximum count (default: `30` frames) to keep processing efficient.
* **Resolution Scaling**: Frames are scaled so that their longest edge is at most `1568px` while preserving the original aspect ratio. This keeps the visual token budget predictable (approximately 1,400 tokens per frame).
* **Audio Extraction & Transcription**: The audio track is resampled to mono 16kHz. It is then transcribed locally using **OpenAI Whisper (defaulting to the highly efficient `large-v3-turbo` model)**. If no audio is detected, the pipeline marks the state as `NO_AUDIO` and bypasses transcription.

### Stage 2: Visual Scene Clustering (`cluster_frames.py`)
To prevent feeding redundant frames to Claude Vision (which increases latency and API costs), the skill performs a localized visual similarity analysis.
* **Algorithm**: The script isolates a central region of interest (ROI) in each frame (to exclude letterboxing or static borders) and computes a 3-channel HSV color histogram.
* **Grouping**: Using greedy clustering based on histogram correlation, frames with high visual similarity (exceeding `--similarity-threshold`) are grouped.
* **Output**: The step selects a single representative frame for each visual cluster, allowing Claude to inspect a diverse set of 5–8 frames instead of evaluating the entire timeline.

### Stage 3: Visual Identification
Claude Vision evaluates the chosen representative frames. It identifies distinct characters based on recurring visual characteristics (such as clothing, hair color, and setting) and produces a mapping of character IDs to names or descriptions.

### Stage 4: Assembly (`build_json_report.py`)
The final stage compiles the extracted metadata, the timestamped transcript, the visual timeline, and character data into structured outputs.

---

## Installation

### Dependencies
The pipeline requires Python 3.8+ and `ffmpeg` installed on your system path.

Install the required Python libraries locally:
```bash
pip install openai-whisper opencv-python-headless numpy Pillow
```

### Installing in Claude Code
```bash
/plugin install video-analyzer@<your-github-username>
```

### Manual Installation (Claude.ai)
1. Download `video-analyzer.skill` from the repository releases.
2. In your Claude.ai account, navigate to **Settings → Skills → Upload skill**.

---

## CLI Usage

While Claude runs these scripts automatically inside the skill environment, you can run them manually on your machine for testing or local processing.

### Step 1: Pre-process the video
```bash
python3 process_video.py /path/to/video.mp4     --fps 0.5     --max-frames 30     --output-dir /tmp/video_work     --model turbo
```
*Note: Passing either `--model turbo` or `--model large-v3-turbo` instructs the preprocessor to load OpenAI's high-speed pruned large model, requiring approximately ~1.4 GB of system memory for the initial download.*

### Step 2: Cluster frames to select key scenes (Optional)
```bash
python3 cluster_frames.py     --frames-dir /tmp/video_work/frames     --output /tmp/video_work/clusters.json     --manifest /tmp/video_work/manifest.json     --similarity-threshold 0.72
```
*Outputs: `clusters.json` detailing the visual scene transitions.*

### Step 3: Compile the final structured report
```bash
python3 build_json_report.py     --work-dir /tmp/video_work     --output ./output_report.json     --visual-timeline '[{"timestamp":"00:00:00","description":"Subject enters the room."}]'     --character-names '{"1":"Subject A","2":"Subject B"}'     --summary "Brief summary of the video content."     --key-observations '["Observation A", "Observation B"]'
```

---

## Parameters

| Parameter | Default | Description |
|-----------|---------|-------------|
| `--fps` | `0.5` | Frames per second to extract. Increase for fast-cut videos (try `1.0`), decrease for static videos (try `0.2`). |
| `--max-frames` | `30` | Hard cap on frames extracted to keep processing cost within reasonable boundaries. |
| `--model` | `turbo` | Whisper model option. Accepts: `tiny` / `base` / `small` / `medium` / `large` / `turbo` (or `large-v3-turbo`). |
| `--similarity-threshold` | `0.72` | Histogram correlation threshold (0 to 1). Higher values yield stricter scene classification and more clusters. |

---

## Output Structure

The execution generates both a machine-readable `.json` document and a human-readable `.md` report.

### JSON Schema
```json
{
  "schema_version": "1.0",
  "generated_by": "video-analyzer skill",
  "metadata": {
    "filename": "video.mp4",
    "duration_seconds": 120.0,
    "duration_formatted": "00:02:00",
    "size_mb": 15.4,
    "video_codec": "h264",
    "width": 1920,
    "height": 1080,
    "fps_original": 30.0,
    "audio_codec": "aac"
  },
  "characters": {
    "count": 2,
    "count_source": "claude_vision",
    "list": [
      { "character_id": 1, "name": "Subject A" }
    ]
  },
  "audio": {
    "has_audio": true,
    "language_detected": "en",
    "transcript_segments": [
      { "timestamp": "00:00:02", "text": "Hello and welcome." }
    ]
  },
  "visual_timeline": [
    { "timestamp": "00:00:00", "description": "Intro screen with title card." }
  ],
  "summary": "Example video summary.",
  "key_observations": []
}
```

---

## Technical Notes & System Behavior

### 1. Accuracy and Performance (Whisper large-v3-turbo)
The pipeline leverages OpenAI's `large-v3-turbo` model, which optimizes processing efficiency by reducing decoder layers from 32 to 4. This architecture guarantees significantly faster processing speeds with an almost imperceptible loss in accuracy compared to the standard `large-v3`. Multilingual support (including Italian) is fully integrated and delivers transcription accuracy that easily outperforms the `medium` model. Native transcription and direct translation into English (via the `--task translate` flag) are fully supported. 

### 2. Vision-Based Character Tracking
Character identification is handled via visual analysis of keyframes using Vision LLMs rather than a dedicated, rigid facial-recognition database. This flexible, context-aware approach allows the system to recognize and track characters even in complex, stylized, or animated environments where traditional biometrics would fail. Because it relies on overall visual assessment of representative frames, precision is optimal for main characters and clear shots, while serving as a high-level estimate in massive crowds or for brief background appearances. 

### 3. Structural Scene Clustering
The scene clustering algorithm detects transitions by analyzing structural variations in color distribution and lighting within the HSV color space. This method provides an extremely efficient, lightweight solution for isolating camera cuts, editing choices, and distinct scene changes. The system is engineered to map visual timeline continuity and structural breaks rather than track semantic context or individual human movement within a single continuous shot. 

### 4. Streamlined Timeline Transcription
The transcription module outputs a single, chronological text timeline optimized for seamless readability and immediate integration with the video manifest. To keep the local environment lightweight, cross-platform, and free from external dependencies or API registration keys (such as HuggingFace tokens for PyAnnote), the system processes the audio track as a continuous stream without performing speaker diarization (speaker partitioning). 
---

## License

This project is open-source and available under the [MIT License](LICENSE).
