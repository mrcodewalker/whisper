# -*- coding: utf-8 -*-
from flask import Flask, request, jsonify, send_from_directory, url_for
from redis import Redis
from flask_cors import CORS
from rq import Queue
from jobs import enqueue_stt_job, enqueue_merge_job
from datetime import datetime
import os, uuid

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
redis_conn = Redis.from_url(REDIS_URL)
q = Queue("meeting-jobs", connection=redis_conn)

app = Flask(__name__)
allowed_origins = [
    "https://localhost:8080",
    "https://36.50.54.109:8081",
    "https://36.50.54.109:8082",
]
CORS(app, origins=allowed_origins, supports_credentials=True)
MEETINGS_DIR = os.getenv("MEETINGS_DIR", "meetings")
os.makedirs(MEETINGS_DIR, exist_ok=True)


@app.route("/api/stt_input", methods=["POST"])
def stt_input():
    f = request.files.get("file")
    meeting_id = request.form.get("meeting_id")
    user_id = request.form.get("user_id")
    full_name = request.form.get("full_name", "")
    role = request.form.get("role", "")
    ts = request.form.get("ts")

    if not f or not meeting_id or not user_id:
        return jsonify({"error": "missing file or meeting_id or user_id"}), 400

    meeting_dir = os.path.join(MEETINGS_DIR, meeting_id)
    chunks_dir = os.path.join(meeting_dir, "chunks")
    os.makedirs(chunks_dir, exist_ok=True)

    if not ts:
        ts_dt = datetime.utcnow()
    else:
        try:
            ts_dt = datetime.strptime(ts, "%Y-%m-%d %H:%M:%S")
        except ValueError:
            ts_dt = datetime.utcnow()

    ts_str = ts_dt.strftime("%d-%m-%Y_%H-%M-%S")  # dd-mm-yyyy_HH-MM-SS
    fname = f"{ts_str}__{user_id}__{uuid.uuid4().hex}.wav"
    path = os.path.join(chunks_dir, fname)
    f.save(path)

    # Enqueue STT job to transcribe the audio
    try:
        job = q.enqueue(enqueue_stt_job, meeting_id, user_id, full_name, role, ts_str, path, job_timeout=900)
        return jsonify({"status": "saved", "meeting_id": meeting_id, "user_id": user_id, "job_id": job.id}), 202
    except Exception as e:
        return jsonify({"status": "saved", "meeting_id": meeting_id, "user_id": user_id, "error": str(e)}), 202


@app.route("/api/meeting_files/<meeting_id>", methods=["GET"])
def list_meeting_files(meeting_id):
    file_type = request.args.get("type", "chunks").lower()
    
    if file_type not in ["chunks", "final"]:
        return jsonify({"error": "type must be 'chunks' or 'final'"}), 400
    
    meeting_dir = os.path.join(MEETINGS_DIR, meeting_id, file_type)
    if not os.path.exists(meeting_dir):
        return jsonify({"error": f"meeting_id not found or {file_type} folder does not exist"}), 404

    files = []
    for fname in os.listdir(meeting_dir):
        fpath = os.path.join(meeting_dir, fname)
        if os.path.isfile(fpath):
            try:
                date_part = fname.split("__")[0]  # dd-mm-yyyy_HH-MM-SS
                dt = datetime.strptime(date_part, "%d-%m-%Y_%H-%M-%S")
                date_str = dt.strftime("%d/%m/%Y %H:%M:%S")
            except Exception:
                date_str = ""
            
            file_size = os.path.getsize(fpath)
            
            if file_type == "chunks":
                file_url = url_for('download_meeting_file', meeting_id=meeting_id, filename=fname, _external=True)
            else:  # final
                file_url = url_for('download_merged_file', meeting_id=meeting_id, filename=fname, _external=True)
            
            files.append({
                "filename": fname,
                "date": date_str,
                "size": file_size,
                "url": file_url
            })

    return jsonify({"meeting_id": meeting_id, "type": file_type, "files": files})


@app.route("/api/meeting_files/<meeting_id>/<filename>", methods=["GET"])
def download_meeting_file(meeting_id, filename):
    meeting_dir = os.path.join(MEETINGS_DIR, meeting_id, "chunks")
    if not os.path.exists(os.path.join(meeting_dir, filename)):
        return jsonify({"error": "file not found"}), 404
    return send_from_directory(meeting_dir, filename, as_attachment=True)


@app.route("/api/merged_file/<meeting_id>/<filename>", methods=["GET"])
def download_merged_file(meeting_id, filename):
    meeting_dir = os.path.join(MEETINGS_DIR, meeting_id, "final")
    if not os.path.exists(os.path.join(meeting_dir, filename)):
        return jsonify({"error": "file not found"}), 404
    return send_from_directory(meeting_dir, filename, as_attachment=True)


@app.route("/api/merge_audio", methods=["POST"])
def merge_audio():
    j = request.get_json() or {}
    meeting_id = j.get("meeting_id")
    if not meeting_id:
        return jsonify({"error": "missing meeting_id"}), 400

    meeting_dir = os.path.join(MEETINGS_DIR, meeting_id)
    chunks_dir = os.path.join(meeting_dir, "chunks")

    if not os.path.exists(chunks_dir) or not os.listdir(chunks_dir):
        return jsonify({"error": "no audio chunks found"}), 400

    # Enqueue merge job to run in background
    try:
        job = q.enqueue(enqueue_merge_job, meeting_id, job_timeout=3600)
        return jsonify({
            "status": "merge_queued",
            "meeting_id": meeting_id,
            "job_id": job.id,
            "check_status_url": url_for('check_merge_status', job_id=job.id, _external=True)
        }), 202
    except Exception as e:
        return jsonify({
            "status": "error",
            "meeting_id": meeting_id,
            "error": str(e)
        }), 500


@app.route("/api/merge_status/<job_id>", methods=["GET"])
def check_merge_status(job_id):
    try:
        job = q.fetch_job(job_id)
        if not job:
            return jsonify({"error": "job not found"}), 404
        
        response = {
            "job_id": job_id,
            "status": job.get_status(),
        }
        
        # If job is finished, include the result
        if job.is_finished:
            result = job.result
            if result:
                response["output"] = result.get("output")
                if result.get("output"):
                    response["url"] = url_for('download_merged_file', 
                                            meeting_id=result.get("output", "").split("/")[1], 
                                            filename=os.path.basename(result.get("output", "")), 
                                            _external=True)
        
        # If job failed, include the error
        if job.is_failed:
            response["error"] = str(job.exc_info)
        
        return jsonify(response), 200
    except Exception as e:
        return jsonify({
            "error": f"Error checking job status: {str(e)}"
        }), 500


@app.route("/api/merge_transcript", methods=["POST"])
def merge_transcript():
    """
    Merge all transcripts from cache and create a DOCX file
    """
    j = request.get_json() or {}
    meeting_id = j.get("meeting_id")
    
    if not meeting_id:
        return jsonify({"error": "missing meeting_id"}), 400
    
    meeting_dir = os.path.join(MEETINGS_DIR, meeting_id)
    final_dir = os.path.join(meeting_dir, "final")
    
    try:
        os.makedirs(final_dir, exist_ok=True)
        
        # Enqueue merge transcript job
        from jobs import enqueue_merge_transcript_job
        job = q.enqueue(enqueue_merge_transcript_job, meeting_id, job_timeout=600)
        
        return jsonify({
            "status": "merge_transcript_queued",
            "meeting_id": meeting_id,
            "job_id": job.id,
            "check_status_url": url_for('check_merge_transcript_status', job_id=job.id, _external=True)
        }), 202
    except Exception as e:
        return jsonify({
            "status": "error",
            "meeting_id": meeting_id,
            "error": str(e)
        }), 500


@app.route("/api/merge_transcript_status/<job_id>", methods=["GET"])
def check_merge_transcript_status(job_id):
    """
    Check status of merge transcript job
    """
    try:
        job = q.fetch_job(job_id)
        if not job:
            return jsonify({"error": "job not found"}), 404
        
        response = {
            "job_id": job_id,
            "status": job.get_status(),
        }
        
        if job.is_finished:
            result = job.result
            if result:
                response["output"] = result.get("output")
                if result.get("output"):
                    meeting_id = result.get("meeting_id")
                    filename = os.path.basename(result.get("output", ""))
                    response["download_url"] = url_for('download_transcript_file', 
                                                      meeting_id=meeting_id, 
                                                      filename=filename, 
                                                      _external=True)
        
        if job.is_failed:
            response["error"] = str(job.exc_info)
        
        return jsonify(response), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/transcript_file/<meeting_id>/<filename>", methods=["GET"])
def download_transcript_file(meeting_id, filename):
    """Download transcript DOCX file"""
    meeting_dir = os.path.join(MEETINGS_DIR, meeting_id, "final")
    if not os.path.exists(os.path.join(meeting_dir, filename)):
        return jsonify({"error": "file not found"}), 404
    return send_from_directory(meeting_dir, filename, as_attachment=True)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)