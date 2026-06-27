#!/usr/bin/env python3
"""
build_pdf_report.py — PDF report generator for the video-analyzer skill.

Primary renderer : weasyprint  (install: pip install weasyprint)
Fallback renderer: reportlab   (install: pip install reportlab)

Can be imported as a module (generate_pdf) or run as a standalone script.

Usage (standalone):
    python3 build_pdf_report.py \
        --json-report /path/to/report.json \
        --frames-dir  /tmp/video_work/frames \
        --output-dir  /path/to/outputs
"""

import argparse
import base64
import html
import json
import os
import re
import sys
from datetime import date
from xml.sax.saxutils import escape as _xe

# Single authoritative version string — defined in scripts/version.py
_here = os.path.dirname(os.path.abspath(__file__))
if _here not in sys.path:
    sys.path.insert(0, _here)
from version import __version__ as _SKILL_VERSION

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# ── Renderer detection ────────────────────────────────────────────────────────
_HAS_WEASYPRINT = False
_HAS_REPORTLAB  = False

try:
    from weasyprint import HTML as _WP_HTML
    _HAS_WEASYPRINT = True
except Exception:
    pass

try:
    from reportlab.lib.pagesizes import A4 as _RL_A4
    from reportlab.lib.styles import getSampleStyleSheet as _RL_STYLES
    from reportlab.lib.styles import ParagraphStyle as _RL_PS
    from reportlab.lib.units import mm as _RL_MM
    from reportlab.lib import colors as _RL_COLORS
    from reportlab.platypus import (
        SimpleDocTemplate as _RL_DOC,
        Paragraph as _RL_P,
        Spacer as _RL_SP,
        Table as _RL_TABLE,
        TableStyle as _RL_TS,
        HRFlowable as _RL_HR,
        Image as _RL_IMG,
    )
    _HAS_REPORTLAB = True
except Exception:
    pass

# ── Inline CSS (weasyprint path) ──────────────────────────────────────────────
_CSS = """
@page { size: A4; margin: 20mm; }
*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
body {
    font-family: system-ui, -apple-system, Arial, sans-serif;
    color: #222; background: #fff; font-size: 10pt; line-height: 1.5;
}
header {
    background: #1a1a2e; color: #fff;
    padding: 14pt 18pt; margin-bottom: 20pt; border-radius: 5pt;
}
header h1  { font-size: 15pt; font-weight: 700; margin-bottom: 4pt; }
header .sub { font-size: 8.5pt; opacity: 0.75; }
.section   { margin-bottom: 20pt; }
.section h2 {
    font-size: 12pt; font-weight: 700; color: #1a1a2e;
    border-bottom: 2px solid #e94560; padding-bottom: 3pt; margin-bottom: 10pt;
}
table.data { width: 100%; border-collapse: collapse; font-size: 9pt; }
table.data th {
    background: #1a1a2e; color: #fff;
    padding: 5pt 8pt; text-align: left; font-weight: 600;
}
table.data td { padding: 5pt 8pt; border-bottom: 1px solid #eee; vertical-align: top; }
table.data tr:nth-child(even) td { background: #f8f8f8; }
table.thumbs {
    width: 100%; border-collapse: separate; border-spacing: 7pt 7pt;
}
table.thumbs td { width: 33%; vertical-align: top; text-align: center; }
table.thumbs img {
    width: 100%; max-height: 85pt; object-fit: cover;
    border-radius: 3pt; display: block;
}
.thumb-ts   { font-family: monospace; font-size: 7.5pt; color: #e94560; margin-top: 3pt; }
.thumb-desc { font-size: 7.5pt; color: #555; margin-top: 2pt; line-height: 1.3; }
.tl-node {
    padding: 6pt 0; border-bottom: 1px solid #f0f0f0;
    display: flex; gap: 10pt; align-items: flex-start;
}
.tl-ts {
    font-family: monospace; font-size: 8.5pt; color: #e94560;
    font-weight: 700; white-space: nowrap; min-width: 68pt; padding-top: 2pt;
}
.tl-body { flex: 1; }
.tl-text { font-size: 9pt; margin-bottom: 3pt; }
ul.obs { padding-left: 16pt; font-size: 9.5pt; }
ul.obs li { margin-bottom: 3pt; }
.tx-summary {
    margin-bottom: 8pt; padding: 5pt 10pt;
    background: #fff8e1; border-left: 3px solid #e94560;
    font-size: 9pt; font-weight: 600;
}
.tx-row { padding: 4pt 0; border-bottom: 1px solid #f0f0f0; display: flex; gap: 10pt; }
.tx-ts  { font-family: monospace; font-size: 8.5pt; color: #e94560; font-weight: 700; white-space: nowrap; min-width: 68pt; padding-top: 1pt; }
.tx-text { flex: 1; font-size: 9pt; }
.tx-low  { color: #888888; font-style: italic; }
.tx-badge { display: inline-block; border: 1px solid #cccccc; border-radius: 2pt; padding: 0 4pt; font-size: 7pt; color: #888888; font-style: normal; margin-right: 4pt; vertical-align: middle; }
.src-audio {
    display: inline; background: #1a6e4f; color: #fff;
    padding: 1pt 5pt; border-radius: 2pt; font-size: 7pt; font-weight: 700;
    font-style: normal; margin-right: 5pt; vertical-align: middle;
}
.src-vision {
    display: inline; background: #5a3e9a; color: #fff;
    padding: 1pt 5pt; border-radius: 2pt; font-size: 7pt; font-weight: 700;
    font-style: normal; margin-right: 5pt; vertical-align: middle;
}
.vision-line { font-style: italic; color: #5a3e9a; font-size: 9pt; margin-bottom: 2pt; }
.thumb-desc-vision { font-size: 7.5pt; color: #5a3e9a; font-style: italic; margin-top: 2pt; line-height: 1.3; }
.disclaimer {
    background: #f5f5f5; border-left: 3pt solid #888888;
    padding: 7pt 10pt; font-size: 8.5pt; margin-bottom: 16pt; line-height: 1.5;
}
footer {
    text-align: center; font-size: 8pt; color: #aaa;
    margin-top: 22pt; padding-top: 8pt; border-top: 1px solid #eee;
}
"""

# ── Helpers ───────────────────────────────────────────────────────────────────
def _ts_to_secs(ts_str):
    """Parse HH:MM:SS or HH:MM:SS.mmm → float seconds."""
    try:
        parts = re.split(r"[:\.]", ts_str)
        h_  = int(parts[0])
        mn_ = int(parts[1])
        s_  = int(parts[2])
        ms_ = int(parts[3]) if len(parts) > 3 else 0
        return h_ * 3600 + mn_ * 60 + s_ + ms_ / 1000.0
    except (ValueError, IndexError):
        return 0.0


def _img_b64(path):
    """Return a data:image/jpeg;base64,… URI for the file at path."""
    with open(path, "rb") as f:
        return "data:image/jpeg;base64," + base64.b64encode(f.read()).decode("ascii")


def _build_thumbnails(visual_timeline, frames_dir):
    """
    Return [{path, ts, desc}] for up to 12 scene_*.jpg frames in frames_dir,
    captioned by the closest visual_timeline entry by timestamp.
    Returns [] (never raises) if frames_dir is missing or empty.
    """
    if not os.path.isdir(frames_dir):
        return []

    jpgs = sorted(
        os.path.join(frames_dir, f)
        for f in os.listdir(frames_dir)
        if f.startswith("scene_") and f.endswith(".jpg")
    )[:12]

    if not jpgs:
        return []

    # Read manifest for frame → timestamp mapping
    work_dir = os.path.dirname(os.path.abspath(frames_dir))
    manifest_map = {}
    m_path = os.path.join(work_dir, "manifest.json")
    if os.path.exists(m_path):
        with open(m_path, encoding="utf-8") as f:
            raw = json.load(f)
        for entry in (raw if isinstance(raw, list) else []):
            fname = os.path.basename(entry.get("path", ""))
            manifest_map[fname] = (
                entry.get("timestamp_seconds", 0.0),
                entry.get("timestamp_formatted", ""),
            )

    def caption_for(ts_secs):
        if not visual_timeline:
            return ""
        closest = min(
            visual_timeline,
            key=lambda e: abs(_ts_to_secs(e.get("timestamp", "00:00:00")) - ts_secs),
        )
        return (closest.get("description") or "")[:80]

    results = []
    for path in jpgs:
        fname = os.path.basename(path)
        ts_secs, ts_fmt = manifest_map.get(fname, (0.0, fname))
        results.append({
            "path": path,
            "ts":   ts_fmt or fname,
            "desc": caption_for(ts_secs),
        })
    return results


# ── HTML builder (weasyprint) ─────────────────────────────────────────────────
def _build_html(report, nodes, thumbnails, today_str):
    h    = html.escape
    meta = report.get("metadata", {})
    chars = report.get("characters", {}).get("list", [])
    obs   = report.get("key_observations", [])

    filename = meta.get("filename", "Video")
    duration = meta.get("duration_formatted", "–")

    audio_info      = report.get("audio", {})
    transcript_segs = audio_info.get("transcript_segments", [])
    n_total      = len(transcript_segs)
    n_low        = sum(1 for s in transcript_segs if s.get("low_confidence") is True)
    lang_note_raw = (audio_info.get("language_note") or
                     audio_info.get("language_detected", "–"))
    lang_note     = h(lang_note_raw)
    conf_summary = (
        f"Trascrizione: {n_total} segmenti totali, "
        f"{n_low} a bassa confidenza (da verificare manualmente)"
    )

    parts = [
        "<!DOCTYPE html>",
        "<html lang='it'><head><meta charset='utf-8'>",
        f"<title>{h(filename)} — Report</title>",
        f"<style>{_CSS}</style>",
        "</head><body>",
    ]

    # ── Header ────────────────────────────────────────────────────────────────
    parts.append(
        f"<header>"
        f"<h1>{h(filename)}</h1>"
        f"<div class='sub'>Durata: {h(duration)} &nbsp;|&nbsp; "
        f"Analizzato: {today_str} &nbsp;|&nbsp; video-analyzer skill v{_SKILL_VERSION}</div>"
        f"<div class='sub'>{h(conf_summary)}</div>"
        f"</header>"
    )
    parts.append(
        "<div class='disclaimer'>"
        "<b>Nota sulle sorgenti:</b> "
        "I testi con <span class='src-audio'>🎤 audio</span> sono trascrizioni Whisper "
        "verificabili riascoltando il video originale. "
        "Le descrizioni con <span class='src-vision'>👁 visione</span> sono generate da "
        "Claude Vision analizzando singoli fotogrammi: inferenza automatica, "
        "può contenere errori di interpretazione."
        "</div>"
    )

    # ── Section 1 — Metadata ──────────────────────────────────────────────────
    w        = meta.get("width")  or "–"
    ht       = meta.get("height") or "–"
    fps      = meta.get("fps_original") or "–"
    n_scenes = len([n for n in nodes if n.get("visual_delta") is not None])
    n_chars  = report.get("characters", {}).get("count", 0)

    meta_rows = [
        ("Filename",               h(filename)),
        ("Durata",                 h(duration)),
        ("Risoluzione",            f"{w}×{ht}"),
        ("FPS originale",          str(fps)),
        ("Codec video",            h(str(meta.get("video_codec",  "–")))),
        ("Codec audio",            h(str(meta.get("audio_codec",  "–")))),
        ("Bitrate",                f"{meta.get('bitrate_kbps', '–')} kbps"),
        ("Dimensione",             f"{meta.get('size_mb', '–')} MB"),
        ("Lingua",                  lang_note),
        ("Personaggi identificati",str(n_chars)),
        ("Scene con delta visivo", str(n_scenes)),
    ]
    parts.append("<div class='section'><h2>1. Metadata</h2>"
                 "<table class='data'><tr><th>Proprietà</th><th>Valore</th></tr>")
    for prop, val in meta_rows:
        parts.append(f"<tr><td>{prop}</td><td>{val}</td></tr>")
    parts.append("</table></div>")

    # ── Section 2 — Characters ────────────────────────────────────────────────
    parts.append("<div class='section'><h2>2. Personaggi</h2>"
                 "<table class='data'><tr>"
                 "<th>ID</th><th>Nome</th><th>Prima apparizione</th><th>Apparizioni</th>"
                 "</tr>")
    if chars:
        for c in chars:
            cid         = h(str(c.get("character_id", "–")))
            name        = h(str(c.get("name",          "–")))
            first_seen  = h(str(c.get("first_seen",    "—")))
            appearances = h(str(c.get("appearances",   "—")))
            parts.append(f"<tr><td>{cid}</td><td>{name}</td><td>{first_seen}</td><td>{appearances}</td></tr>")
    else:
        parts.append("<tr><td colspan='4' style='color:#888'>"
                     "Nessun personaggio identificato.</td></tr>")
    parts.append("</table></div>")

    # ── Section 3 — Thumbnail grid ────────────────────────────────────────────
    parts.append("<div class='section'><h2>3. Scene rilevate</h2>")
    if thumbnails:
        parts.append("<table class='thumbs'>")
        for row_start in range(0, len(thumbnails), 3):
            row = thumbnails[row_start:row_start + 3]
            parts.append("<tr>")
            for thumb in row:
                try:
                    src = _img_b64(thumb["path"])
                    img_tag = f'<img src="{src}" alt="frame {h(thumb["ts"])}">'
                except Exception:
                    img_tag = ""
                ts_s     = h(thumb["ts"])
                raw_desc = thumb["desc"]
                desc_s   = (
                    f"<span class='src-vision'>👁 visione</span> {h(raw_desc)}"
                    if raw_desc else ""
                )
                parts.append(
                    f"<td>{img_tag}"
                    f"<div class='thumb-ts'>[{ts_s}]</div>"
                    f"<div class='thumb-desc-vision'>{desc_s}</div></td>"
                )
            for _ in range(3 - len(row)):
                parts.append("<td></td>")
            parts.append("</tr>")
        parts.append("</table>")
    else:
        parts.append("<p style='color:#888'>Nessun thumbnail disponibile — cartella frames/ non trovata.</p>")
    parts.append("</div>")

    # ── Section 4 — Timeline ──────────────────────────────────────────────────
    parts.append("<div class='section'><h2>4. Timeline</h2>")
    for node in nodes:
        raw_ats    = (node.get("anchor_ts") or "")[:8]
        ts_val     = h(raw_ats) if raw_ats else "[timestamp non disponibile]"
        text_val   = h(node.get("text_clean") or node.get("text_raw") or "")
        visual_val = node.get("visual_delta") or ""
        show_vis   = bool(visual_val) and visual_val not in ("analisi frame", "vision_error")
        raw_vts    = (node.get("visual_delta_ts") or raw_ats)
        vis_ts     = h(raw_vts) if raw_vts else "[timestamp non disponibile]"
        audio_html = (
            f"<p class='tl-text'>"
            f"<span class='src-audio'>🎤 audio</span>{text_val}</p>"
            if text_val else ""
        )
        vision_html = (
            f"<p class='vision-line'>"
            f"<span class='tl-ts' style='min-width:auto;padding-right:6pt'>[{vis_ts}]</span>"
            f"<span class='src-vision'>👁 visione</span>{h(visual_val)}</p>"
            if show_vis else ""
        )
        parts.append(
            f"<div class='tl-node'>"
            f"<span class='tl-ts'>[{ts_val}]</span>"
            f"<div class='tl-body'>"
            f"{audio_html}"
            f"{vision_html}"
            f"</div></div>"
        )
    if not nodes:
        parts.append("<p style='color:#888'>Nessun nodo disponibile.</p>")
    parts.append("</div>")

    # ── Section 5 — Trascrizione ──────────────────────────────────────────────
    parts.append(
        "<div class='section'>"
        "<h2>5. Trascrizione <span class='src-audio'>🎤 audio</span></h2>"
    )
    full_summary = f"{conf_summary} · Lingua: {lang_note_raw}"
    parts.append(f"<div class='tx-summary'>{h(full_summary)}</div>")
    if transcript_segs:
        for seg in transcript_segs:
            raw_ts = seg.get("timestamp", "")
            ts_s   = h(raw_ts) if raw_ts else "[timestamp non disponibile]"
            text_s = h(seg.get("text", ""))
            lc     = seg.get("low_confidence")  # True, False, or None
            if lc is True:
                parts.append(
                    f"<div class='tx-row'>"
                    f"<span class='tx-ts'>[{ts_s}]</span>"
                    f"<span class='tx-text tx-low'>"
                    f"<span class='tx-badge'>⚠️ incerto</span>{text_s}</span>"
                    f"</div>"
                )
            elif lc is None:
                parts.append(
                    f"<div class='tx-row'>"
                    f"<span class='tx-ts'>[{ts_s}]</span>"
                    f"<span class='tx-text'>{text_s}"
                    f" <span class='tx-badge'>conf. n/d</span></span>"
                    f"</div>"
                )
            else:
                parts.append(
                    f"<div class='tx-row'>"
                    f"<span class='tx-ts'>[{ts_s}]</span>"
                    f"<span class='tx-text'>{text_s}</span>"
                    f"</div>"
                )
    else:
        parts.append("<p style='color:#888'>Nessun segmento trascrizione disponibile.</p>")
    parts.append("</div>")

    # ── Section 6 — Key observations ──────────────────────────────────────────
    parts.append("<div class='section'><h2>6. Osservazioni Chiave</h2>")
    if obs:
        parts.append("<ul class='obs'>")
        for item in obs:
            parts.append(f"<li>{h(str(item))}</li>")
        parts.append("</ul>")
    else:
        parts.append("<p style='color:#888'>Nessuna osservazione inserita.</p>")
    parts.append("</div>")

    # ── Footer ────────────────────────────────────────────────────────────────
    parts.append(f"<footer>Generated by video-analyzer skill v{_SKILL_VERSION} — {today_str}</footer>")
    parts.append("</body></html>")

    return "\n".join(parts)


# ── Reportlab builder (fallback) ──────────────────────────────────────────────
def _build_pdf_reportlab(report, nodes, thumbnails, output_path, today_str):
    meta     = report.get("metadata", {})
    chars    = report.get("characters", {}).get("list", [])
    obs      = report.get("key_observations", [])
    filename = meta.get("filename", "Video")
    duration = meta.get("duration_formatted", "–")

    audio_info      = report.get("audio", {})
    transcript_segs = audio_info.get("transcript_segments", [])
    n_total      = len(transcript_segs)
    n_low        = sum(1 for s in transcript_segs if s.get("low_confidence") is True)
    lang_note_rl = (audio_info.get("language_note") or
                    audio_info.get("language_detected", "–"))
    conf_summary = (
        f"Trascrizione: {n_total} segmenti totali, "
        f"{n_low} a bassa confidenza (da verificare manualmente)"
    )

    doc = _RL_DOC(
        output_path, pagesize=_RL_A4,
        leftMargin=20*_RL_MM, rightMargin=20*_RL_MM,
        topMargin=20*_RL_MM, bottomMargin=20*_RL_MM,
    )

    styles = _RL_STYLES()
    ACCENT      = _RL_COLORS.HexColor("#e94560")
    DARK        = _RL_COLORS.HexColor("#1a1a2e")
    GREY        = _RL_COLORS.HexColor("#888888")
    AUDIO_C     = _RL_COLORS.HexColor("#1a6e4f")
    VISION_C    = _RL_COLORS.HexColor("#5a3e9a")

    H1 = _RL_PS("va_h1", parent=styles["Normal"],
                 fontSize=16, fontName="Helvetica-Bold",
                 textColor=DARK, spaceAfter=4)
    H2 = _RL_PS("va_h2", parent=styles["Normal"],
                 fontSize=12, fontName="Helvetica-Bold",
                 textColor=DARK, spaceBefore=16, spaceAfter=2)
    BODY        = styles["Normal"]
    SMALL       = _RL_PS("va_small",      parent=BODY,  fontSize=8)
    CONF_SUM    = _RL_PS("va_conf_sum",   parent=SMALL, fontSize=8,
                          textColor=DARK, fontName="Helvetica-Bold",
                          leftIndent=6,   borderPad=4, spaceBefore=2, spaceAfter=6)
    LOW_CONF    = _RL_PS("va_low_conf",   parent=BODY,  fontSize=9,
                          fontName="Helvetica-Oblique", textColor=GREY)
    UNKCONF     = _RL_PS("va_unkconf",    parent=BODY,  fontSize=9, textColor=GREY)
    VISION_BODY = _RL_PS("va_vision",     parent=BODY,  fontSize=8,
                          fontName="Helvetica-Oblique", textColor=VISION_C)
    DISCLAIMER  = _RL_PS("va_disclaimer", parent=BODY,  fontSize=8,
                          leftIndent=8,   rightIndent=8, spaceBefore=4, spaceAfter=10,
                          leading=12)

    page_w = doc.width
    story  = []

    # Title
    story.append(_RL_P(filename, H1))
    story.append(_RL_P(
        f"Durata: {duration} | Analizzato: {today_str} | video-analyzer skill v{_SKILL_VERSION}",
        SMALL,
    ))
    story.append(_RL_P(conf_summary, CONF_SUM))
    story.append(_RL_P(
        '<b>Nota sulle sorgenti:</b> '
        f'<font color="#1a6e4f"><b>[🎤 audio]</b></font> = trascrizione Whisper, '
        'verificabile riascoltando il video originale. '
        f'<font color="#5a3e9a"><b>[👁 visione]</b></font> = Claude Vision su singoli '
        'fotogrammi: inferenza automatica, può contenere errori.',
        DISCLAIMER,
    ))
    story.append(_RL_HR(width="100%", color=ACCENT, thickness=1, spaceAfter=8))
    story.append(_RL_SP(0, 6))

    # ── Section 1 — Metadata ──────────────────────────────────────────────────
    story.append(_RL_P("1. Metadata", H2))
    story.append(_RL_HR(width="100%", color=ACCENT, thickness=1, spaceAfter=8))
    w  = meta.get("width")  or "–"
    ht = meta.get("height") or "–"
    n_scenes = len([n for n in nodes if n.get("visual_delta") is not None])
    meta_data = [
        ["Proprietà", "Valore"],
        ["Filename",              filename],
        ["Durata",                duration],
        ["Risoluzione",           f"{w}×{ht}"],
        ["FPS originale",         str(meta.get("fps_original") or "–")],
        ["Codec video",           str(meta.get("video_codec",  "–"))],
        ["Codec audio",           str(meta.get("audio_codec",  "–"))],
        ["Dimensione",            f"{meta.get('size_mb', '–')} MB"],
        ["Lingua",                lang_note_rl],
        ["Personaggi",            str(report.get("characters", {}).get("count", 0))],
        ["Scene con delta visivo",str(n_scenes)],
    ]
    meta_tbl = _RL_TABLE(meta_data, colWidths=[0.40*page_w, 0.60*page_w])
    meta_tbl.setStyle(_RL_TS([
        ("BACKGROUND",   (0, 0), (-1, 0), DARK),
        ("TEXTCOLOR",    (0, 0), (-1, 0), _RL_COLORS.white),
        ("FONTNAME",     (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE",     (0, 0), (-1,-1), 9),
        ("ROWBACKGROUNDS",(0,1), (-1,-1), [_RL_COLORS.white, _RL_COLORS.HexColor("#f8f8f8")]),
        ("GRID",         (0, 0), (-1,-1), 0.5, _RL_COLORS.HexColor("#dddddd")),
        ("TOPPADDING",   (0, 0), (-1,-1), 4),
        ("BOTTOMPADDING",(0, 0), (-1,-1), 4),
        ("LEFTPADDING",  (0, 0), (-1,-1), 6),
    ]))
    story.append(meta_tbl)
    story.append(_RL_SP(0, 14))

    # ── Section 2 — Characters ────────────────────────────────────────────────
    story.append(_RL_P("2. Personaggi", H2))
    story.append(_RL_HR(width="100%", color=ACCENT, thickness=1, spaceAfter=8))
    char_data = [["ID", "Nome", "Prima app.", "Apparizioni"]]
    for c in chars:
        char_data.append([
            str(c.get("character_id", "–")),
            str(c.get("name",          "–")),
            str(c.get("first_seen",    "—")),
            str(c.get("appearances",   "—")),
        ])
    if not chars:
        char_data.append(["–", "Nessun personaggio identificato", "–", "–"])
    char_tbl = _RL_TABLE(char_data, colWidths=[0.12*page_w, 0.42*page_w, 0.23*page_w, 0.23*page_w])
    char_tbl.setStyle(_RL_TS([
        ("BACKGROUND",   (0, 0), (-1, 0), DARK),
        ("TEXTCOLOR",    (0, 0), (-1, 0), _RL_COLORS.white),
        ("FONTNAME",     (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE",     (0, 0), (-1,-1), 9),
        ("ROWBACKGROUNDS",(0,1), (-1,-1), [_RL_COLORS.white, _RL_COLORS.HexColor("#f8f8f8")]),
        ("GRID",         (0, 0), (-1,-1), 0.5, _RL_COLORS.HexColor("#dddddd")),
        ("TOPPADDING",   (0, 0), (-1,-1), 4),
        ("BOTTOMPADDING",(0, 0), (-1,-1), 4),
        ("LEFTPADDING",  (0, 0), (-1,-1), 6),
    ]))
    story.append(char_tbl)
    story.append(_RL_SP(0, 14))

    # ── Section 3 — Thumbnail grid ────────────────────────────────────────────
    story.append(_RL_P("3. Scene rilevate", H2))
    story.append(_RL_HR(width="100%", color=ACCENT, thickness=1, spaceAfter=8))
    if thumbnails:
        THUMB_W = (page_w - 20) / 3
        THUMB_H = 75
        for batch_start in range(0, min(len(thumbnails), 9), 3):
            batch = thumbnails[batch_start:batch_start + 3]
            while len(batch) < 3:
                batch = batch + [None]
            img_row, ts_row, desc_row = [], [], []
            for t in batch:
                if t is None:
                    img_row.append(""); ts_row.append(""); desc_row.append("")
                else:
                    try:
                        img_row.append(_RL_IMG(t["path"], width=THUMB_W, height=THUMB_H, kind="bound"))
                    except Exception:
                        img_row.append(_RL_P("(err)", SMALL))
                    ts_row.append(_RL_P(
                        f'<font color="#e94560">[{_xe(t["ts"])}]</font>', SMALL))
                    desc_row.append(_RL_P(
                        (f'<font color="#5a3e9a"><i>👁 {_xe(t["desc"][:70])}</i></font>'
                         if t["desc"] else "—"),
                        SMALL))
            grid_tbl = _RL_TABLE(
                [img_row, ts_row, desc_row],
                colWidths=[THUMB_W + 6] * 3,
            )
            grid_tbl.setStyle(_RL_TS([
                ("VALIGN",        (0, 0), (-1, -1), "TOP"),
                ("ALIGN",         (0, 0), (-1, -1), "CENTER"),
                ("TOPPADDING",    (0, 0), (-1, -1), 2),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
            ]))
            story.append(grid_tbl)
            story.append(_RL_SP(0, 6))
    else:
        story.append(_RL_P("Nessun thumbnail disponibile — cartella frames/ non trovata.", SMALL))
    story.append(_RL_SP(0, 14))

    # ── Section 4 — Timeline ──────────────────────────────────────────────────
    story.append(_RL_P("4. Timeline", H2))
    story.append(_RL_HR(width="100%", color=ACCENT, thickness=1, spaceAfter=8))
    for node in nodes:
        raw_ats   = (node.get("anchor_ts") or "")[:8]
        ts_s      = _xe(raw_ats) if raw_ats else "[timestamp non disponibile]"
        text_s    = _xe(node.get("text_clean") or node.get("text_raw") or "")
        visual_s  = node.get("visual_delta") or ""
        show_vis  = bool(visual_s) and visual_s not in ("analisi frame", "vision_error")
        raw_vts   = node.get("visual_delta_ts") or raw_ats
        vis_ts    = _xe(raw_vts) if raw_vts else "[timestamp non disponibile]"
        if text_s:
            story.append(_RL_P(
                f'<font color="#e94560"><b>[{ts_s}]</b></font>'
                f'  <font color="#1a6e4f"><b>[🎤]</b></font>  {text_s}',
                BODY,
            ))
        if show_vis:
            story.append(_RL_P(
                f'<font color="#e94560">[{vis_ts}]</font>'
                f'  <font color="#5a3e9a"><i>[👁 visione]  {_xe(visual_s)}</i></font>',
                VISION_BODY,
            ))
        story.append(_RL_SP(0, 5))
    if not nodes:
        story.append(_RL_P("Nessun nodo disponibile.", SMALL))
    story.append(_RL_SP(0, 14))

    # ── Section 5 — Trascrizione ──────────────────────────────────────────────
    story.append(_RL_P(
        '5. Trascrizione  <font color="#1a6e4f"><b>[🎤 audio]</b></font>', H2))
    story.append(_RL_HR(width="100%", color=ACCENT, thickness=1, spaceAfter=8))
    story.append(_RL_P(f"{conf_summary} · Lingua: {_xe(lang_note_rl)}", CONF_SUM))
    if transcript_segs:
        for seg in transcript_segs:
            raw_ts = seg.get("timestamp", "")
            ts_s   = _xe(raw_ts) if raw_ts else "[timestamp non disponibile]"
            text_s = _xe(seg.get("text", ""))
            lc     = seg.get("low_confidence")  # True, False, or None
            if lc is True:
                story.append(_RL_P(
                    f'<font color="#e94560"><b>[{ts_s}]</b></font>'
                    f'  <font color="#e94560"><b>[⚠ incerto]</b></font>'
                    f'  <font color="#888888"><i>{text_s}</i></font>',
                    LOW_CONF,
                ))
            elif lc is None:
                story.append(_RL_P(
                    f'<font color="#e94560"><b>[{ts_s}]</b></font>'
                    f'  {text_s}'
                    f'  <font color="#888888">[conf. n/d]</font>',
                    UNKCONF,
                ))
            else:
                story.append(_RL_P(
                    f'<font color="#e94560"><b>[{ts_s}]</b></font>  {text_s}',
                    BODY,
                ))
            story.append(_RL_SP(0, 2))
    else:
        story.append(_RL_P("Nessun segmento trascrizione disponibile.", SMALL))
    story.append(_RL_SP(0, 14))

    # ── Section 6 — Key observations ──────────────────────────────────────────
    story.append(_RL_P("6. Osservazioni Chiave", H2))
    story.append(_RL_HR(width="100%", color=ACCENT, thickness=1, spaceAfter=8))
    if obs:
        for item in obs:
            story.append(_RL_P(f"• {_xe(str(item))}", BODY))
    else:
        story.append(_RL_P("Nessuna osservazione inserita.", SMALL))
    story.append(_RL_SP(0, 12))

    # Footer
    footer_style = _RL_PS("va_footer", parent=SMALL, alignment=1,
                           textColor=_RL_COLORS.HexColor("#aaaaaa"))
    story.append(_RL_HR(width="100%", color=_RL_COLORS.HexColor("#dddddd"),
                        thickness=0.5, spaceAfter=4))
    story.append(_RL_P(f"Generated by video-analyzer skill v{_SKILL_VERSION} — {today_str}", footer_style))

    doc.build(story)


# ── Public API ────────────────────────────────────────────────────────────────
def generate_pdf(json_path, frames_dir, output_dir):
    """
    Generate a PDF report from the JSON output and frame images.

    Args:
        json_path  : Path to the JSON report from build_json_report.py
        frames_dir : Path to the frames/ directory with extracted scene JPEGs
        output_dir : Directory where the PDF will be written

    Returns:
        Absolute path of the generated PDF.

    Raises:
        RuntimeError  if neither weasyprint nor reportlab is available.
        FileNotFoundError if json_path does not exist.
    """
    if not _HAS_WEASYPRINT and not _HAS_REPORTLAB:
        raise RuntimeError(
            "No PDF renderer available.\n"
            "Install one:  pip install weasyprint   OR   pip install reportlab"
        )

    with open(json_path, encoding="utf-8") as f:
        report = json.load(f)

    nodes           = report.get("rag_timeline", [])
    visual_timeline = report.get("visual_timeline", [])
    thumbnails      = _build_thumbnails(visual_timeline, frames_dir)

    video_stem = os.path.splitext(report.get("metadata", {}).get("filename", "video"))[0]
    pdf_name   = f"{video_stem}_report.pdf"
    os.makedirs(output_dir, exist_ok=True)
    output_path = os.path.join(output_dir, pdf_name)

    today_str = date.today().strftime("%Y-%m-%d")

    if _HAS_WEASYPRINT:
        try:
            html_str = _build_html(report, nodes, thumbnails, today_str)
            _WP_HTML(string=html_str).write_pdf(output_path)
            size_kb = os.path.getsize(output_path) // 1024
            print(f"✅ PDF report written to {output_path}  ({size_kb} KB, weasyprint)",
                  flush=True)
            return output_path
        except Exception as e:
            print(f"   weasyprint failed: {e}", flush=True)
            if not _HAS_REPORTLAB:
                raise
            print("   Falling back to reportlab …", flush=True)

    _build_pdf_reportlab(report, nodes, thumbnails, output_path, today_str)
    size_kb = os.path.getsize(output_path) // 1024
    print(f"✅ PDF report written to {output_path}  ({size_kb} KB, reportlab)", flush=True)
    return output_path


# ── Standalone CLI ─────────────────────────────────────────────────────────────
if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Generate a PDF report from the video-analyzer JSON output."
    )
    parser.add_argument("--json-report", required=True, help="Path to the JSON report")
    parser.add_argument("--frames-dir",  required=True, help="Path to the frames/ directory")
    parser.add_argument("--output-dir",  required=True, help="Output directory for the PDF")
    cli = parser.parse_args()

    renderer = ("weasyprint" if _HAS_WEASYPRINT
                else "reportlab" if _HAS_REPORTLAB
                else "none")
    print(f"Renderer: {renderer}", flush=True)

    out = generate_pdf(cli.json_report, cli.frames_dir, cli.output_dir)
    print(f"Done: {out}", flush=True)
