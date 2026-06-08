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

Upload any video and run manually:

```bash
python3 video-analyzer/scripts/process_video.py /path/to/test.mp4 \
    --fps 0.5 --max-frames 20 --output-dir /tmp/test_work

python3 video-analyzer/scripts/detect_characters.py \
    --frames-dir /tmp/test_work/frames \
    --output /tmp/test_work/characters.json \
    --manifest /tmp/test_work/manifest.json

cat /tmp/test_work/characters.json
```

## Submitting to anthropics/skills

1. Fork https://github.com/anthropics/skills
2. Copy the `video-analyzer/` folder into `skills/`
3. Open a pull request with:
   - A brief description of what the skill does
   - A test video result (or screenshot of a report)

## Ideas for improvement

- [ ] Face embedding clustering for live-action video (e.g. `face_recognition` lib)
- [ ] Scene-change detection with ffmpeg's `select='gt(scene,0.4)'`
- [ ] PDF output via the existing `pdf` skill
- [ ] Support for YouTube URLs (yt-dlp integration)
- [ ] Subtitle/SRT extraction alongside Whisper transcript
