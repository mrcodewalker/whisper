# -*- coding: utf-8 -*-
import os
from utils import merge_audio_chunks, build_docx_and_pdf, build_transcript_from_cache
from datetime import datetime

MEETINGS_DIR = os.getenv("MEETINGS_DIR", "meetings")

def enqueue_stt_job(meeting_id, user_id, full_name, role, ts, filepath):
    from utils import transcribe_with_whisper, append_transcript_cache
    text = transcribe_with_whisper(filepath)
    entry = {
        "ts": ts,
        "user_id": user_id,
        "full_name": full_name,
        "role": role,
        "text": text,
        "source_file": filepath
    }
    append_transcript_cache(meeting_id, entry)
    return {"meeting_id": meeting_id, "user_id": user_id, "text_len": len(text)}

def enqueue_merge_job(meeting_id):
    meeting_dir = os.path.join(MEETINGS_DIR, meeting_id)
    chunks_dir = os.path.join(meeting_dir, "chunks")
    final_dir = os.path.join(meeting_dir, "final")
    os.makedirs(final_dir, exist_ok=True)
    log_path = os.path.join(meeting_dir, "merge.log")
    timestamp = datetime.utcnow().strftime("%d-%m-%Y_%H-%M-%S")
    merged_base = os.path.join(final_dir, f"merged_{timestamp}")
    
    audio_outputs = {}
    with open(log_path, "a", encoding="utf-8") as log:
        log.write(f"\n=== Merge started at {datetime.utcnow()} ===\n")
        log.write(f"Chunks dir: {chunks_dir}\n")
        log.write(f"Output base: {merged_base}\n")
        try:
            if not os.path.exists(chunks_dir) or not os.listdir(chunks_dir):
                raise RuntimeError("No audio chunks to merge")
            audio_outputs = merge_audio_chunks(chunks_dir, merged_base)
            log.write(f"Merge completed successfully!\n")
            log.write(f"Merged wav: {audio_outputs['wav']}\n")
            log.write(f"Merged ogg: {audio_outputs['ogg']}\n")
        except Exception as e:
            log.write(f"Merge failed: {e}\n")
            raise
        finally:
            log.write(f"=== Merge ended at {datetime.utcnow()} ===\n")
    
    transcript_entries = build_transcript_from_cache(meeting_id)
    documents = build_docx_and_pdf(meeting_id, transcript_entries, final_dir)

    with open(log_path, "a", encoding="utf-8") as log:
        log.write(f"Transcript entries: {len(transcript_entries)}\n")
        log.write(f"DOCX: {documents['docx']}\n")
        log.write(f"PDF: {documents['pdf']}\n")
        log.write(f"Signature: {documents['signature']}\n")

    return {
        "status": "merged",
        "audio": audio_outputs,
        "documents": documents,
    }
