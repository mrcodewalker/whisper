# -*- coding: utf-8 -*-
from flask import Flask, request, jsonify, send_from_directory, url_for
from flask_cors import CORS
from jobs import enqueue_job
from datetime import datetime
import os, uuid
from utils import try_convert_docx_to_pdf_libreoffice


from flask import Flask, request, jsonify
from cryptography.hazmat.primitives import serialization, hashes
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
from cryptography import x509
from cryptography.hazmat.primitives.serialization import pkcs12 
import datetime


app = Flask(__name__)
allowed_origins = [
    "https://localhost:8080",
    "https://36.50.54.109:8081",
    "https://36.50.54.109:8082",
    "http://localhost:4200",
    "https://localhost:4200",
    "https://meeting.kolla.click",
    "https://meeting.kolla.click/"
]
CORS(app, origins=allowed_origins, supports_credentials=True)
MEETINGS_DIR = os.getenv("MEETINGS_DIR", "meetings")
os.makedirs(MEETINGS_DIR, exist_ok=True)

@app.route("/api/stt_input", methods=["POST"])
def stt_input():
    """
    API to handle speech-to-text requests. Ensures jobs are processed in order.
    """
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

    # Enqueue STT job to transcribe the audio using Thread Pool
    try:
        enqueue_job("stt", meeting_id, user_id, full_name, role, ts_str, path)
        return jsonify({"status": "queued", "meeting_id": meeting_id, "user_id": user_id}), 202
    except Exception as e:
        return jsonify({"status": "error", "meeting_id": meeting_id, "user_id": user_id, "error": str(e)}), 500


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

    # Enqueue merge job to run in background using Thread Pool
    try:
        enqueue_job("merge_audio", meeting_id)
        return jsonify({"status": "merge_queued", "meeting_id": meeting_id}), 202
    except Exception as e:
        return jsonify({"status": "error", "meeting_id": meeting_id, "error": str(e)}), 500


@app.route("/api/merge_status/<job_id>", methods=["GET"])
def check_merge_status(job_id):
    return jsonify({"error": "merge status checking is not available with Thread Pool"}), 501


@app.route("/api/transcript_file/<meeting_id>/<filename>", methods=["GET"])
def download_transcript_file(meeting_id, filename):
    """Download transcript DOCX file"""
    meeting_dir = os.path.join(MEETINGS_DIR, meeting_id, "final")
    if not os.path.exists(os.path.join(meeting_dir, filename)):
        return jsonify({"error": "file not found"}), 404
    return send_from_directory(meeting_dir, filename, as_attachment=True)


@app.route("/api/convert_pdf", methods=["POST"])
def convert_pdf():
    """
    API to convert a DOCX file of a meeting to a signed PDF file.
    """
    j = request.get_json() or {}
    meeting_id = j.get("meeting_id")

    if not meeting_id:
        return jsonify({"error": "missing meeting_id"}), 400

    meeting_dir = os.path.join(MEETINGS_DIR, meeting_id, "final")
    if not os.path.exists(meeting_dir):
        return jsonify({"error": "meeting directory not found"}), 404

    # Find the DOCX file
    docx_files = [f for f in os.listdir(meeting_dir) if f.endswith(".docx")]
    if not docx_files:
        return jsonify({"error": "no DOCX file found in meeting directory"}), 404

    docx_path = os.path.join(meeting_dir, docx_files[0])
    pdf_path = os.path.join(meeting_dir, os.path.splitext(docx_files[0])[0] + ".pdf")

    try:
        # Convert DOCX to PDF
        success = try_convert_docx_to_pdf_libreoffice(docx_path, pdf_path)
        if not success:
            return jsonify({"error": "failed to convert DOCX to PDF"}), 500

    except Exception as e:
        return jsonify({"error": "failed to convert PDF", "details": str(e)}), 500


@app.route("/api/queue_status", methods=["GET"])
def queue_status():
    """API to get the status of all jobs in the queue."""
    return jsonify({"error": "queue status checking is not available with Thread Pool"}), 501


@app.route('/create_key', methods=['POST'])
def create_key():
    try:
        # Lấy dữ liệu từ JSON request
        data = request.get_json()
        user_id = data.get('user_id')
        user_name = data.get('user_name')

        if not user_id or not user_name:
            return jsonify({"error": "user_id và user_name là bắt buộc"}), 400

        # 1. Tạo Private Key
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)

        # 2. Tạo Certificate tự ký
        sign_text = user_id + user_name
        subject = issuer = x509.Name([
            x509.NameAttribute(NameOID.COMMON_NAME, sign_text),
        ])
        cert = (
            x509.CertificateBuilder()
            .subject_name(subject)
            .issuer_name(issuer)
            .public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(datetime.datetime.now(datetime.timezone.utc))
            .not_valid_after(datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=10))
            .sign(key, hashes.SHA256())
        )

        # 3. Lưu thành file .pfx (PKCS#12)
        with open("{user_name}-{user_id}.pfx", "wb") as f:
            # SỬA DÒNG NÀY: Dùng trực tiếp pkcs12.serialize... thay vì serialization.pkcs12...
            f.write(pkcs12.serialize_key_and_certificates(
                f"{user_id}-{user_name}".encode(), key, cert, None, serialization.BestAvailableEncryption(f"actvn@edu.vn{user_id}-{user_name}".encode())
            ))

        return jsonify({"message": "Tạo key thành công", "key": "{user_name}-{user_id}.pfx"}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)