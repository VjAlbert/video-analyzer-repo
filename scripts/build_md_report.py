import json
import sys
import os

def build_md(json_path, md_path):
    with open(json_path, 'r', encoding='utf-8') as f:
        data = json.load(f)

    meta = data.get("metadata", {})
    audio = data.get("audio", {})
    segs = audio.get("transcript_segments", [])
    
    total_segments = len(segs)
    low_conf_segments = sum(1 for s in segs if s.get("low_confidence") is True)
    
    # 1. Metadata Table
    meta_props = [
        ("Filename", f'`{meta.get("filename", "")}`'),
        ("Durata", f'`{meta.get("duration_formatted", "")}`'),
        ("Risoluzione", f'`{meta.get("width", "")}x{meta.get("height", "")}`'),
        ("Video codec", f'`{meta.get("video_codec", "")}`'),
        ("Audio codec", f'`{meta.get("audio_codec", "")}`'),
        ("Dimensione", f'`{meta.get("size_mb", "")} MB`'),
        ("FPS", f'`{meta.get("fps_original", "")}`'),
        ("Bitrate", f'`{meta.get("bitrate_kbps", "")} kbps`'),
        ("Whisper model", f'`{meta.get("whisper_model", "")}`'),
        ("Vision model", f'`{meta.get("vision_model", "")}`'),
    ]
    meta_table_str = "\n".join(f"| {k} | {v} |" for k, v in meta_props)
    
    # 2. Characters Identified
    chars_list = data.get("characters", {}).get("list", [])
    chars_count = data.get("characters", {}).get("count", len(chars_list))
    
    chars_rows = []
    for char in chars_list:
        cid = char.get("character_id", "")
        fullname = char.get("name", "")
        # Extract name and description from our custom formatted string "Name - Description"
        if " - " in fullname:
            name, desc = fullname.split(" - ", 1)
        else:
            name, desc = fullname, "n/d"
        chars_rows.append(f"| {cid} | {name.strip()} | {desc.strip()} |")
    chars_table_str = "\n".join(chars_rows)
    
    # 3. Transcription Audio Lines
    lang_note = audio.get("language_note", "")
    lang_prob = meta.get("language_detection_prob")
    
    lang_warning = ""
    if lang_prob is not None and lang_prob < 0.60:
        lang_warning = "\n>\n> ⚠️ Rilevamento lingua incerto — se il video contiene più lingue o audio poco chiaro, la trascrizione può contenere errori sistematici."
        
    transcript_lines = []
    for seg in segs:
        ts = seg.get("timestamp", "")
        text = seg.get("text", "").strip()
        low_conf = seg.get("low_confidence")
        
        if low_conf is True:
            line = f"*⚠️ [trascrizione incerta] [{ts}] {text}*"
        elif low_conf is False:
            line = f"[{ts}] {text}"
        else:
            line = f"[{ts}] {text} [confidenza non disponibile]"
        transcript_lines.append(line)
    transcript_str = "\n".join(transcript_lines)
    
    # 4. Visual Timeline
    v_timeline = data.get("visual_timeline", [])
    v_timeline_str = ""
    for idx, vt in enumerate(v_timeline):
        ts = vt.get("timestamp", "")
        desc = vt.get("description", "")
        v_timeline_str += f"### [{ts}] — Scena {idx+1}\n> 👁 [descrizione automatica immagine] {desc}\n\n"
    v_timeline_str = v_timeline_str.strip()
    
    # 5. Key Observations
    key_obs = data.get("key_observations", [])
    key_obs_str = "\n".join(f"- {obs}" for obs in key_obs)
    
    # Construct Markdown
    md_content = f"""# 📹 Video Report: {meta.get("filename", "")}
> Auto-generato dalla skill video-analyzer.

> **Trascrizione: {total_segments} segmenti totali, {low_conf_segments} a bassa confidenza (da verificare manualmente)**
>
> **Nota sulle sorgenti:** Il testo in sezione 3 (🎤 audio) proviene dalla trascrizione
> Whisper ed è verificabile riascoltando il video. Le descrizioni in sezione 4
> (👁 visione) sono generate da Claude Vision su singoli fotogrammi: inferenza automatica,
> può contenere errori.

## 1. Metadata
| Proprietà | Valore |
|-----------|--------|
{meta_table_str}

## 2. Personaggi Identificati
*({chars_count} personaggi distinti identificati da Claude Vision)*

| ID | Nome/Label | Descrizione |
|----|-----------|-------------|
{chars_table_str}

## 3. Trascrizione Audio — 🎤 sorgente: Whisper (verificabile riascoltando il video)
*({total_segments} segmenti totali · {low_conf_segments} a bassa confidenza · Whisper `{meta.get("whisper_model", "")}` · Lingua: {lang_note})*

> **Trascrizione: {total_segments} segmenti totali, {low_conf_segments} a bassa confidenza (da verificare manualmente) · Lingua: {lang_note}**{lang_warning}

{transcript_str}

## 4. Timeline Visiva — 👁 sorgente: Claude Vision (interpretazione automatica di fotogrammi)

> **Nota:** Le descrizioni seguenti sono generate da Claude Vision analizzando singoli
> fotogrammi estratti dal video. Si tratta di inferenza automatica: può contenere errori
> di identificazione, attribuzione o interpretazione. Non equivale alla trascrizione audio.

{v_timeline_str}

## 5. Sommario AI
{data.get("summary", "")}

## 6. Osservazioni Chiave
{key_obs_str}
"""
    
    with open(md_path, 'w', encoding='utf-8') as f:
        f.write(md_content)
    print(f"Markdown report written to {md_path}")

if __name__ == '__main__':
    if len(sys.argv) < 3:
        print("Usage: python build_md_report.py <json_path> <md_path>")
        sys.exit(1)
    build_md(sys.argv[1], sys.argv[2])
