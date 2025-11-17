# -*- coding: utf-8 -*-
from flask import Flask, request, jsonify, send_from_directory, url_for
from flask_cors import CORS
from jobs import enqueue_job
from datetime import datetime
import os, uuid
from utils import try_convert_docx_to_pdf_libreoffice

from pyhanko.sign.general import load_cert_from_pemder
from pyhanko.sign.signers import SimpleSigner, PdfSigner, PdfSignatureMetadata
from pyhanko.sign.fields import append_signature_field

from pyhanko.pdf_utils.incremental_writer import IncrementalPdfFileWriter
from pyhanko.sign import fields
from pyhanko.pdf_utils.writer import PageObject


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
        return jsonify({"error": f"Meeting ID {meeting_id} not found or no final directory exists"}), 404

    # Find the DOCX file
    docx_files = [f for f in os.listdir(meeting_dir) if f.endswith(".docx")]
    if not docx_files:
        return jsonify({"error": "No DOCX file found for the meeting"}), 404

    docx_path = os.path.join(meeting_dir, docx_files[0])
    pdf_path = os.path.join(meeting_dir, os.path.splitext(docx_files[0])[0] + ".pdf")

    try:
        # Convert DOCX to PDF
        success = try_convert_docx_to_pdf_libreoffice(docx_path, pdf_path)
        if not success:
            return jsonify({"error": "Failed to convert DOCX to PDF"}), 500

        # Sign the PDF using pyHanko
        signed_pdf_path = pdf_path.replace(".pdf", "_signed.pdf")
        key_file = os.path.join("meetings", "global_sign", "private.key")
        cert_file = os.path.join("meetings", "global_sign", "public.pem")

        print("Key file path:", key_file)
        print("Cert file path:", cert_file)

        # Load signer
        signer = SimpleSigner.load(key_file, cert_file)


        with open(pdf_path, "rb") as pdf_in, open(signed_pdf_path, "wb") as pdf_out:
            writer = IncrementalPdfFileWriter(pdf_in)

            media_box = writer.reader.pages[-1].media_box

            new_page = PageObject(writer, media_box=media_box)
            writer.add_page(new_page)

            new_page_index = len(writer.reader.pages) - 1

            signature_meta = fields.append_signature_field(
                writer,
                fields.SigFieldSpec(
                    'Signature1',
                    on_page=new_page_index,       # <-- Đặt ở trang mới
                    box=(400, 50, 550, 150)       # <-- Tọa độ góc dưới-phải
                )
            )

            pdf_signer = PdfSigner(
                signature_meta=signature_meta,
                signer=signer
            )

            pdf_signer.sign_pdf(writer, pdf_out)

        return jsonify({
            "status": "success",
            "meeting_id": meeting_id,
            "pdf_file": signed_pdf_path
        }), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/queue_status", methods=["GET"])
def queue_status():
    """API to get the status of all jobs in the queue."""
    return jsonify({"error": "queue status checking is not available with Thread Pool"}), 501


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)