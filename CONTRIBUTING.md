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
# Run preprocessing
python3 scripts/process_video.py /path/to/test.mp4 \
    --fps 0.5 --max-frames 20 --output-dir /tmp/test_work --model turbo

# Run visual scene clustering (checks color/composition similarity)
python3 scripts/cluster_frames.py \
    --frames-dir /tmp/test_work/frames \
    --output /tmp/test_work/clusters.json \
    --manifest /tmp/test_work/manifest.json

# Check the generated cluster metadata
cat /tmp/test_work/clusters.json
```

