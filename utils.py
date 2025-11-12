# -*- coding: utf-8 -*-
import os, json, hashlib, hmac
from redis import Redis
from datetime import datetime
from docx import Document
import subprocess
from pathlib import Path
from typing import List, Dict, Any

SIGNATURE_SECRET = os.getenv("SIGNATURE_SECRET")

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
r = Redis.from_url(REDIS_URL)
MEETINGS_DIR = os.getenv("MEETINGS_DIR", "meetings")

def merge_audio_chunks(chunks_dir, output_base):
    if not os.path.exists(chunks_dir):
        raise RuntimeError("Audio chunks directory does not exist")
    
    files = sorted([f for f in os.listdir(chunks_dir) if f.endswith(".wav")])
    if not files:
        raise RuntimeError("No audio chunks to merge")
    
    files.sort(key=lambda x: x.split("__")[0])
    
    output_base_path = Path(output_base)
    if output_base_path.suffix:
        output_base_path = output_base_path.with_suffix("")

    wav_path = str(output_base_path.with_suffix(".wav"))
    ogg_path = str(output_base_path.with_suffix(".ogg"))
    
    list_txt = os.path.join(chunks_dir, "list.txt")
    with open(list_txt, "w", encoding="utf-8") as f:
        for fname in files:
            fpath = os.path.abspath(os.path.join(chunks_dir, fname))
            f.write(f"file '{fpath}'\n")
    
    cmd_wav = [
        "ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", list_txt,
        "-acodec", "pcm_s16le", "-ar", "48000", "-ac", "1", wav_path
    ]

    cmd_ogg = [
        "ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", list_txt,
        "-c:a", "libopus", "-b:a", "64k", ogg_path
    ]

    try:
        result_wav = subprocess.run(cmd_wav, capture_output=True, text=True)
        if result_wav.returncode != 0:
            raise RuntimeError(f"FFmpeg error when producing wav: {result_wav.stderr}")

        result_ogg = subprocess.run(cmd_ogg, capture_output=True, text=True)
        if result_ogg.returncode != 0:
            raise RuntimeError(f"FFmpeg error when producing ogg: {result_ogg.stderr}")
    finally:
        if os.path.exists(list_txt):
            os.remove(list_txt)
    
    return {"wav": wav_path, "ogg": ogg_path}

def transcribe_with_whisper(filepath):
    try:
        import whisper
    except Exception as e:
        raise RuntimeError("whisper package not installed: " + str(e))
    model = whisper.load_model("base")
    result = model.transcribe(filepath)
    return result.get("text", "").strip()

def append_transcript_cache(meeting_id, entry):
    cache_key = f"meeting:{meeting_id}:transcripts"
    last = r.lindex(cache_key, -1)
    if last:
        last_e = json.loads(last)
        try:
            fmt_ddmmyyyy = "%d-%m-%Y_%H-%M-%S"
            tlast = datetime.strptime(last_e["ts"], fmt_ddmmyyyy)
            tcur = datetime.strptime(entry["ts"], fmt_ddmmyyyy)
            gap = (tcur - tlast).total_seconds()
        except Exception:
            gap = 9999
        if (
            last_e.get("user_id") == entry.get("user_id")
            and (last_e.get("full_name") or "") == (entry.get("full_name") or "")
            and (last_e.get("role") or "") == (entry.get("role") or "")
            and gap <= 35
        ):
            last_e["text"] = (last_e.get("text", "") + " " + entry.get("text", "")).strip()
            last_e["formatted"] = format_transcript_line(last_e)
            r.rpop(cache_key)
            r.rpush(cache_key, json.dumps(last_e, ensure_ascii=False))
            return
    entry["formatted"] = format_transcript_line(entry)
    r.rpush(cache_key, json.dumps(entry, ensure_ascii=False))

def format_transcript_line(entry: Dict[str, Any]) -> str:
    ts_str = entry.get("ts", "")
    full_name = (entry.get("full_name") or "Unknown").strip() or "Unknown"
    role = (entry.get("role") or "N/A").strip() or "N/A"
    text = entry.get("text", "").strip()
    return f"[{ts_str} - {full_name} - {role}] : {text}"


def build_docx_and_pdf(meeting_id, entries, output_dir):
    lines: List[str] = []
    for e in entries:
        if not e.get("formatted"):
            e["formatted"] = format_transcript_line(e)
        lines.append(e["formatted"])

    signature_info = generate_transcript_signature(meeting_id, lines)

    doc = Document()
    doc.add_heading(f"Bien ban cuoc hop: {meeting_id}", level=1)
    doc.add_paragraph(f"Created: {datetime.utcnow().strftime('%d/%m/%Y %H:%M:%S UTC')}")
    doc.add_paragraph("")
    for line in lines:
        doc.add_paragraph(line)
    doc.add_paragraph("")
    doc.add_paragraph(f"Digital signature ({signature_info['algorithm']}): {signature_info['value']}")
    doc.add_paragraph(f"Signature created at: {signature_info['created']}")

    os.makedirs(output_dir, exist_ok=True)
    docx_path = os.path.join(output_dir, f"{meeting_id}.docx")
    doc.save(docx_path)

    pdf_path = os.path.join(output_dir, f"{meeting_id}.pdf")
    pdf_created = create_pdf_with_reportlab(meeting_id, lines, signature_info, pdf_path)
    if not pdf_created:
        try_convert_docx_to_pdf_libreoffice(docx_path, pdf_path)

    signature_path = os.path.join(output_dir, f"{meeting_id}.signature.json")
    with open(signature_path, "w", encoding="utf-8") as sig_file:
        json.dump(signature_info, sig_file, ensure_ascii=False, indent=2)

    return {"docx": docx_path, "pdf": pdf_path, "signature": signature_path, "signature_info": signature_info}

def try_convert_docx_to_pdf_libreoffice(docx_path, pdf_path):
    try:
        outdir = os.path.dirname(pdf_path)
        import subprocess
        cmd = ["soffice", "--headless", "--convert-to", "pdf", "--outdir", outdir, docx_path]
        subprocess.check_call(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        produced = os.path.join(outdir, os.path.splitext(os.path.basename(docx_path))[0] + ".pdf")
        if os.path.exists(produced):
            if produced != pdf_path:
                os.replace(produced, pdf_path)
            return True
    except Exception:
        return False
    return False

def build_transcript_from_cache(meeting_id):
    cache_key = f"meeting:{meeting_id}:transcripts"
    entries = r.lrange(cache_key, 0, -1)
    return [json.loads(e) for e in entries]


def generate_transcript_signature(meeting_id: str, lines: List[str]) -> Dict[str, Any]:
    payload = "\n".join(lines).encode("utf-8")
    timestamp = datetime.utcnow().isoformat(timespec="seconds") + "Z"
    if SIGNATURE_SECRET:
        digest = hmac.new(SIGNATURE_SECRET.encode("utf-8"), payload, hashlib.sha256).hexdigest()
        algorithm = "HMAC-SHA256"
    else:
        digest = hashlib.sha256(payload).hexdigest()
        algorithm = "SHA256"
    return {
        "meeting_id": meeting_id,
        "algorithm": algorithm,
        "value": digest,
        "created": timestamp,
        "line_count": len(lines),
    }


def create_pdf_with_reportlab(meeting_id: str, lines: List[str], signature_info: Dict[str, Any], pdf_path: str) -> bool:
    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.pdfgen import canvas
        from reportlab.lib.units import mm
    except Exception:
        return False

    os.makedirs(os.path.dirname(pdf_path), exist_ok=True)

    page_width, page_height = A4
    left_margin = 20 * mm
    right_margin = 20 * mm
    top_margin = 25 * mm
    bottom_margin = 20 * mm
    text_width = page_width - left_margin - right_margin

    c = canvas.Canvas(pdf_path, pagesize=A4)
    c.setTitle(f"Bien ban cuoc hop: {meeting_id}")
    y = page_height - top_margin

    def write_line(text: str, font_name="Helvetica", font_size=11):
        nonlocal y
        c.setFont(font_name, font_size)
        wrapped = wrap_text_reportlab(c, text, text_width, font_name, font_size)
        for line in wrapped:
            if y < bottom_margin:
                c.showPage()
                y_new = page_height - top_margin
                y = y_new
                c.setFont(font_name, font_size)
            c.drawString(left_margin, y, line)
            y -= 14

    c.setFont("Helvetica-Bold", 16)
    c.drawString(left_margin, y, f"Bien ban cuoc hop: {meeting_id}")
    y -= 24
    write_line(f"Created: {datetime.utcnow().strftime('%d/%m/%Y %H:%M:%S UTC')}", font_size=10)
    y -= 10

    for line in lines:
        write_line(line)

    y -= 10
    write_line(f"Digital signature ({signature_info['algorithm']}): {signature_info['value']}", font_size=10)
    write_line(f"Signature created at: {signature_info['created']}", font_size=10)
    c.showPage()
    c.save()
    return True


def wrap_text_reportlab(canvas_obj, text, max_width, font_name, font_size) -> List[str]:
    words = text.split()
    if not words:
        return [""]
    lines = []
    current = words[0]
    for word in words[1:]:
        trial = f"{current} {word}"
        if canvas_obj.stringWidth(trial, font_name, font_size) <= max_width:
            current = trial
        else:
            lines.append(current)
            current = word
    lines.append(current)
    return lines
