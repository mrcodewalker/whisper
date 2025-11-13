# -*- coding: utf-8 -*-
import os
from utils import merge_audio_chunks, build_docx_and_pdf
from datetime import datetime
from pydub import AudioSegment

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
    merged_wav_path = os.path.join(final_dir, f"merged_{timestamp}.wav")
    merged_ogg_path = os.path.join(final_dir, f"merged_{timestamp}.ogg")
    
    with open(log_path, "a", encoding="utf-8") as log:
        log.write(f"\n=== Merge started at {datetime.utcnow()} ===\n")
        log.write(f"Chunks dir: {chunks_dir}\n")
        log.write(f"Output WAV file: {merged_wav_path}\n")
        log.write(f"Output OGG file: {merged_ogg_path}\n")
        try:
            if not os.path.exists(chunks_dir) or not os.listdir(chunks_dir):
                raise RuntimeError("No audio chunks to merge")
            
            # Merge các file WAV thành 1 file WAV
            merge_audio_chunks(chunks_dir, merged_wav_path)
            log.write(f"WAV merge completed successfully!\n")
            log.write(f"Merged WAV file: {merged_wav_path}\n")
            
            # Chuyển đổi WAV sang OGG
            try:
                audio = AudioSegment.from_wav(merged_wav_path)
                audio.export(merged_ogg_path, format="ogg", bitrate="128k")
                log.write(f"OGG conversion completed successfully!\n")
                log.write(f"Merged OGG file: {merged_ogg_path}\n")
                
                # Xóa file WAV tạm sau khi đã chuyển sang OGG
                if os.path.exists(merged_wav_path):
                    os.remove(merged_wav_path)
                    log.write(f"Temporary WAV file removed: {merged_wav_path}\n")
            except Exception as e:
                log.write(f"OGG conversion failed: {e}\n")
                log.write(f"Keeping WAV file: {merged_wav_path}\n")
                # Không raise exception để vẫn giữ được file WAV nếu chuyển đổi thất bại
            
            # ===== CODE XÓA CÁC FILE CHUNKS (ĐÃ COMMENT) =====
            # Bỏ comment đoạn code dưới đây nếu muốn xóa tất cả file chunks sau khi merge
            # try:
            #     chunk_files = [f for f in os.listdir(chunks_dir) if f.endswith(".wav")]
            #     deleted_count = 0
            #     for chunk_file in chunk_files:
            #         chunk_path = os.path.join(chunks_dir, chunk_file)
            #         try:
            #             os.remove(chunk_path)
            #             deleted_count += 1
            #             log.write(f"Deleted chunk: {chunk_file}\n")
            #         except Exception as e:
            #             log.write(f"Failed to delete {chunk_file}: {e}\n")
            #     log.write(f"Total deleted chunks: {deleted_count}/{len(chunk_files)}\n")
            # except Exception as e:
            #     log.write(f"Error deleting chunks: {e}\n")
            # ===== END CODE XÓA CHUNKS =====
            
        except Exception as e:
            log.write(f"Merge failed: {e}\n")
            raise
        finally:
            log.write(f"=== Merge ended at {datetime.utcnow()} ===\n")
    
    return {"status": "merged", "output": merged_ogg_path if os.path.exists(merged_ogg_path) else merged_wav_path}