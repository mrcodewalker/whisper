# -*- coding: utf-8 -*-
import os, json, hashlib, shutil
from redis import Redis
from datetime import datetime
from pydub import AudioSegment
from docx import Document
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
r = Redis.from_url(REDIS_URL)
MEETINGS_DIR = os.getenv("MEETINGS_DIR", "meetings")


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


def merge_audio_chunks(chunks_dir, out_path):
    if not os.path.exists(chunks_dir):
        raise RuntimeError("audio chunks directory does not exist")
    files = sorted([f for f in os.listdir(chunks_dir) if f.endswith(".wav")])
    combined = None
    for f in files:
        seg = AudioSegment.from_file(os.path.join(chunks_dir, f))
        combined = seg if combined is None else combined + seg
    if combined is None:
        raise RuntimeError("no audio to merge")
    combined.export(out_path, format="wav")
    return out_path


def build_docx_and_pdf(meeting_id, entries, output_dir):
    doc = Document()
    doc.add_heading(f"Biên b?n cu?c h?p: {meeting_id}", level=1)
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
