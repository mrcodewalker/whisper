# -*- coding: utf-8 -*-
import os, json, hashlib, shutil
from redis import Redis
from datetime import datetime
from docx import Document
import subprocess
from pathlib import Path

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
r = Redis.from_url(REDIS_URL)
MEETINGS_DIR = os.getenv("MEETINGS_DIR", "meetings")

def merge_audio_chunks(chunks_dir, out_path):
    if not os.path.exists(chunks_dir):
        raise RuntimeError("Audio chunks directory does not exist")
    
    files = [
        os.path.join(chunks_dir, f)
        for f in os.listdir(chunks_dir)
        if f.lower().endswith(".wav")
    ]
    if not files:
        raise RuntimeError("No audio chunks to merge")
    
    files.sort(key=os.path.getctime)
    
    list_txt = os.path.join(chunks_dir, "list.txt")
    with open(list_txt, "w", encoding="utf-8") as f:
        for fname in files:
            fpath = Path(fname).resolve().as_posix()
            f.write(f"file '{fpath}'\n")
    
    out_path_obj = Path(out_path)
    if out_path_obj.suffix.lower() != ".ogg":
        out_path_obj = out_path_obj.with_suffix(".ogg")
    out_ogg = str(out_path_obj)

    cmd = [
    "ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", list_txt,
    "-c:a", "libopus", "-b:a", "64k", out_ogg
    ]
    
    #cmd = [
    #"ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", list_txt,
    #"-c", "copy", out_ogg
    #]

    
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"FFmpeg error: {result.stderr}")
    if not os.path.exists(out_ogg):
        raise RuntimeError(f"FFmpeg did not produce output file: {out_ogg}")
    
    if os.path.exists(list_txt):
        os.remove(list_txt)
    
    return out_ogg

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
        if last_e.get("user_id") == entry.get("user_id") and gap <= 30:
            last_e["text"] = last_e.get("text", "") + " " + entry.get("text", "")
            r.rpop(cache_key)
            r.rpush(cache_key, json.dumps(last_e))
            return
    r.rpush(cache_key, json.dumps(entry))

def build_docx_and_pdf(meeting_id, entries, output_dir):
    doc = Document()
    doc.add_heading(f"Bien ban cuoc hop: {meeting_id}", level=1)
    doc.add_paragraph(f"Created: {datetime.utcnow().strftime('%d/%m/%Y %H:%M:%S UTC')}")
    doc.add_paragraph("")
    for e in entries:
        ts_str = e.get("ts", "")
        line = f"({ts_str}) {e.get('full_name','Unknown')} - {e.get('role','')}: {e.get('text','')}"
        doc.add_paragraph(line)
    docx_path = os.path.join(output_dir, f"{meeting_id}.docx")
    doc.save(docx_path)
    pdf_path = os.path.join(output_dir, f"{meeting_id}.pdf")
    try_convert_docx_to_pdf_libreoffice(docx_path, pdf_path)
    return docx_path, pdf_path

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
