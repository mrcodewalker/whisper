# -*- coding: utf-8 -*-
import os, shutil
from utils import merge_audio_chunks, build_docx_and_pdf, r
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
    merge_lock_key = f"meeting:{meeting_id}:merge_in_progress"
    try:
        meeting_dir = os.path.join(MEETINGS_DIR, meeting_id)
        audio_dir = os.path.join(meeting_dir, "audio")
        final_dir = os.path.join(meeting_dir, "final")
        os.makedirs(final_dir, exist_ok=True)

        # 1. Merge audio chunks
        merged_audio_path = os.path.join(meeting_dir, f"{meeting_id}_merged.wav")
        merge_audio_chunks(audio_dir, merged_audio_path)

        # 2. Build transcript
        from utils import build_transcript_from_cache
        transcript_text = build_transcript_from_cache(meeting_id)

        # 3. Build docx & pdf
        build_docx_and_pdf(meeting_id, transcript_text, final_dir)

        # 4. Clean audio chunks (optional)
        shutil.rmtree(audio_dir, ignore_errors=True)

    finally:
        # Release merge lock
        r.delete(merge_lock_key)
