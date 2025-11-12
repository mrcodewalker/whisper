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

TEMP_FILE_EXTENSIONS = {".txt", ".tmp", ".log"}
AUDIO_EXTENSIONS = {".wav", ".ogg", ".webm", ".m4a", ".mp3"}


def merge_audio_chunks(chunks_dir, out_path):
    if not os.path.exists(chunks_dir):
        raise RuntimeError("Audio chunks directory does not exist")
    
    # Xóa các file tạm trong chunks (ví dụ: list.txt cũ, log, tmp)
    for entry in os.listdir(chunks_dir):
        entry_path = os.path.join(chunks_dir, entry)
        if not os.path.isfile(entry_path):
            continue
        if Path(entry).suffix.lower() in TEMP_FILE_EXTENSIONS:
            try:
                os.remove(entry_path)
            except Exception:
                pass
    
    # Lấy tất cả file audio được hỗ trợ
    audio_files = [
        f for f in os.listdir(chunks_dir)
        if os.path.isfile(os.path.join(chunks_dir, f)) and Path(f).suffix.lower() in AUDIO_EXTENSIONS
    ]
    if not audio_files:
        raise RuntimeError("No audio chunks to merge")
    
    # Sort theo timestamp trong tên file (dd-mm-yyyy_HH-MM-SS)
    def parse_timestamp(filename):
        try:
            # Format: dd-mm-yyyy_HH-MM-SS__user_id__uuid.wav
            ts_part = filename.split("__")[0]
            return datetime.strptime(ts_part, "%d-%m-%Y_%H-%M-%S")
        except (ValueError, IndexError):
            # Nếu không parse được, dùng creation time làm fallback
            return datetime.fromtimestamp(os.path.getctime(os.path.join(chunks_dir, filename)))
    
    audio_files.sort(key=parse_timestamp)
    
    # Log số lượng file để merge
    print(f"[merge_audio_chunks] Found {len(audio_files)} audio files to merge")
    for i, fname in enumerate(audio_files, 1):
        print(f"[merge_audio_chunks]   {i}. {fname}")
    
    # Tạo list.txt trong thư mục output (final), không phải trong chunks
    out_dir = os.path.dirname(out_path)
    os.makedirs(out_dir, exist_ok=True)
    list_txt = os.path.join(out_dir, "list.txt")
    
    try:
        with open(list_txt, "w", encoding="utf-8") as f:
            for fname in audio_files:
                fpath = Path(os.path.join(chunks_dir, fname)).resolve().as_posix()
                f.write(f"file '{fpath}'\n")
        
        print(f"[merge_audio_chunks] Created file list: {list_txt} with {len(audio_files)} files")
        
        # Đảm bảo output là .ogg
        out_path_obj = Path(out_path)
        if out_path_obj.suffix.lower() != ".ogg":
            out_path_obj = out_path_obj.with_suffix(".ogg")
        out_ogg = str(out_path_obj)

        # Merge và convert sang ogg
        cmd = [
            "ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", list_txt,
            "-c:a", "libopus", "-b:a", "64k", out_ogg
        ]
        
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            raise RuntimeError(f"FFmpeg error: {result.stderr}")
        if not os.path.exists(out_ogg):
            raise RuntimeError(f"FFmpeg did not produce output file: {out_ogg}")
        
        return out_ogg
    finally:
        # Luôn xóa file list.txt sau khi xong
        if os.path.exists(list_txt):
            try:
                os.remove(list_txt)
            except Exception:
                pass


def convert_audio_to_ogg(src_path, dst_path=None, bitrate="64k"):
    """
    Chuẩn hóa một file audio bất kỳ sang .ogg (libopus) để tiện cho quá trình merge.
    Trả về đường dẫn file đích (.ogg).
    """
    src = Path(src_path)
    if not src.exists():
        raise RuntimeError(f"Source audio file does not exist: {src_path}")
    
    if dst_path is None:
        dst = src.with_suffix(".ogg")
    else:
        dst = Path(dst_path)
    dst.parent.mkdir(parents=True, exist_ok=True)
    
    # Nếu file đã là .ogg thì chỉ cần đổi tên (nếu cần)
    if src.suffix.lower() == ".ogg" and src.resolve() == dst.resolve():
        return str(dst)
    
    cmd = [
        "ffmpeg", "-y", "-i", str(src),
        "-c:a", "libopus", "-b:a", bitrate,
        str(dst)
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"FFmpeg convert error: {result.stderr}")
    
    if src.resolve() != dst.resolve():
        try:
            os.remove(src)
        except Exception:
            pass
    
    return str(dst)

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
