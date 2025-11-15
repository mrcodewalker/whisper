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
    log_path = os.path.join(meeting_dir, "merge.log")
    timestamp = datetime.utcnow().strftime("%d-%m-%Y_%H-%M-%S")
    merged_wav_path = None
    merged_ogg_path = None
    
    try:
        os.makedirs(final_dir, exist_ok=True)
        
        with open(log_path, "a", encoding="utf-8") as log:
            log.write(f"\n=== Merge started at {datetime.utcnow()} ===\n")
            log.write(f"Meeting ID: {meeting_id}\n")
            log.write(f"Chunks dir: {chunks_dir}\n")
            log.write(f"Final dir: {final_dir}\n")
            log.flush()
            
            try:
                if not os.path.exists(chunks_dir):
                    raise RuntimeError(f"Chunks directory does not exist: {chunks_dir}")
                
                if not os.listdir(chunks_dir):
                    raise RuntimeError("No audio chunks to merge")
                
                merged_wav_path = os.path.join(final_dir, f"merged_{timestamp}.wav")
                merged_ogg_path = os.path.join(final_dir, f"merged_{timestamp}.ogg")
                log.write(f"Output WAV file: {merged_wav_path}\n")
                log.write(f"Output OGG file: {merged_ogg_path}\n")
                log.flush()
                
                try:
                    old_ogg_files = [f for f in os.listdir(final_dir) if f.endswith(".ogg")]
                    deleted_count = 0
                    for old_ogg_file in old_ogg_files:
                        old_ogg_path = os.path.join(final_dir, old_ogg_file)
                        try:
                            os.remove(old_ogg_path)
                            deleted_count += 1
                            log.write(f"Deleted old OGG file: {old_ogg_file}\n")
                        except Exception as e:
                            log.write(f"Failed to delete {old_ogg_file}: {e}\n")
                    log.write(f"Total deleted old OGG files: {deleted_count}/{len(old_ogg_files)}\n")
                    log.flush()
                except Exception as e:
                    log.write(f"Error deleting old OGG files: {e}\n")
                    log.flush()

                log.write("Starting WAV merge...\n")
                log.flush()
                merge_audio_chunks(chunks_dir, merged_wav_path)
                log.write(f"WAV merge completed successfully!\n")
                log.write(f"Merged WAV file: {merged_wav_path}\n")
                log.flush()

                log.write("Starting OGG conversion...\n")
                log.flush()
                try:
                    audio = AudioSegment.from_wav(merged_wav_path)
                    audio.export(merged_ogg_path, format="ogg", bitrate="128k")
                    log.write("OGG conversion completed successfully!\n")
                    log.write(f"Merged OGG file: {merged_ogg_path}\n")
                    log.flush()

                    if os.path.exists(merged_wav_path):
                        os.remove(merged_wav_path)
                        log.write(f"Temporary WAV file removed: {merged_wav_path}\n")
                        log.flush()
                except Exception as e:
                    log.write(f"OGG conversion failed: {e}\n")
                    log.write(f"Error type: {type(e).__name__}\n")
                    import traceback
                    log.write(f"Traceback: {traceback.format_exc()}\n")
                    log.write(f"Keeping WAV file: {merged_wav_path}\n")
                    log.flush()
                    raise

            except Exception as e:
                log.write(f"Merge failed: {e}\n")
                log.write(f"Error type: {type(e).__name__}\n")
                import traceback
                log.write(f"Traceback: {traceback.format_exc()}\n")
                log.flush()
                raise

            finally:
                log.write(f"=== Merge ended at {datetime.utcnow()} ===\n")
                log.flush()

    except Exception as e:
        try:
            with open(log_path, "a", encoding="utf-8") as log:
                log.write(f"\n=== CRITICAL ERROR at {datetime.utcnow()} ===\n")
                log.write(f"Error: {e}\n")
                log.write(f"Error type: {type(e).__name__}\n")
                import traceback
                log.write(f"Traceback: {traceback.format_exc()}\n")
                log.flush()
        except:
            pass
        raise

    return {
        "status": "merged",
        "output": merged_ogg_path if merged_ogg_path and os.path.exists(merged_ogg_path) else (merged_wav_path if merged_wav_path and os.path.exists(merged_wav_path) else None)
    }
