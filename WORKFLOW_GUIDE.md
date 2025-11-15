# 📋 Hướng Dẫn Luồng Xử Lý Transcript

## 🔄 Luồng Xử Lý Hoàn Chỉnh

```
1. Upload Audio File
         ↓
2. File được lưu vào meetings/{meeting_id}/chunks/
         ↓
3. Job STT (Speech-to-Text) được queue
         ↓
4. Worker xử lý: Whisper chuyển audio → text
         ↓
5. Transcript được lưu vào Redis cache
         ↓
6. Gọi API merge_transcript
         ↓
7. Toàn bộ transcripts từ cache → DOCX file
         ↓
8. Download file DOCX
```

---

## 📌 API Endpoints

### **1. Upload Audio & Trigger STT**

**Endpoint:** `POST /api/stt_input`

**Content-Type:** `multipart/form-data`

**Parameters:**
- `file` (required): Audio file (.wav, .mp3, etc.)
- `meeting_id` (required): ID of the meeting
- `user_id` (required): ID of the user speaking
- `full_name` (optional): Full name of the user
- `role` (optional): Role of the user (e.g., "participant", "speaker")
- `ts` (optional): Timestamp in format `YYYY-MM-DD HH:MM:SS`

**Example:**
```bash
curl -X POST http://localhost:5000/api/stt_input \
  -F "file=@audio.wav" \
  -F "meeting_id=19" \
  -F "user_id=1" \
  -F "full_name=John Doe" \
  -F "role=participant"
```

**Response:**
```json
{
  "status": "saved",
  "meeting_id": "19",
  "user_id": "1",
  "job_id": "c44ef5a1-3b14-4f21-be38-58b1d25b1f31"
}
```

---

### **2. Check STT Job Status (Optional)**

**Endpoint:** `GET /api/merge_transcript_status/{job_id}`

**Example:**
```bash
curl http://localhost:5000/api/merge_transcript_status/c44ef5a1-3b14-4f21-be38-58b1d25b1f31
```

**Response:**
```json
{
  "job_id": "c44ef5a1-3b14-4f21-be38-58b1d25b1f31",
  "status": "finished"
}
```

---

### **3. Merge Transcripts & Create DOCX**

**Endpoint:** `POST /api/merge_transcript`

**Content-Type:** `application/json`

**Parameters:**
- `meeting_id` (required): ID of the meeting

**Example:**
```bash
curl -X POST http://localhost:5000/api/merge_transcript \
  -H "Content-Type: application/json" \
  -d '{"meeting_id": "19"}'
```

**Response:**
```json
{
  "status": "merge_transcript_queued",
  "meeting_id": "19",
  "job_id": "a8c3f2e1-9b7d-4a6c-8e2f-1d5b9c7a3f6e",
  "check_status_url": "http://localhost:5000/api/merge_transcript_status/a8c3f2e1-9b7d-4a6c-8e2f-1d5b9c7a3f6e"
}
```

---

### **4. Check Merge Transcript Status**

**Endpoint:** `GET /api/merge_transcript_status/{job_id}`

**Example:**
```bash
curl http://localhost:5000/api/merge_transcript_status/a8c3f2e1-9b7d-4a6c-8e2f-1d5b9c7a3f6e
```

**Response (pending):**
```json
{
  "job_id": "a8c3f2e1-9b7d-4a6c-8e2f-1d5b9c7a3f6e",
  "status": "started"
}
```

**Response (finished):**
```json
{
  "job_id": "a8c3f2e1-9b7d-4a6c-8e2f-1d5b9c7a3f6e",
  "status": "finished",
  "output": "meetings/19/final/transcript_19_15-11-2025_22-47-37.docx",
  "download_url": "http://localhost:5000/api/transcript_file/19/transcript_19_15-11-2025_22-47-37.docx"
}
```

---

### **5. Download Transcript DOCX File**

**Endpoint:** `GET /api/transcript_file/{meeting_id}/{filename}`

**Example:**
```bash
curl -O http://localhost:5000/api/transcript_file/19/transcript_19_15-11-2025_22-47-37.docx
```

---

## 📂 File Structure

```
meetings/
├── 19/
│   ├── chunks/
│   │   ├── 15-11-2025_22-47-37__1__uuid.wav    # Uploaded audio files
│   │   ├── 15-11-2025_22-48-08__1__uuid.wav
│   │   └── ...
│   ├── final/
│   │   ├── transcript_19_15-11-2025_22-47-37.docx  # Generated DOCX
│   │   ├── merged_13-11-2025_07-13-17.ogg          # Merged audio (from /api/merge_audio)
│   │   └── ...
│   └── merge.log
```

---

## 🔧 Redis Cache Structure

**Key:** `meeting:{meeting_id}:transcripts`

**Value:** List of JSON objects

**Example:**
```redis
meeting:19:transcripts = [
  {
    "ts": "15-11-2025_22-47-37",
    "user_id": "1",
    "full_name": "John Doe",
    "role": "participant",
    "text": "Xin chào, đây là cuộc họp đầu tiên...",
    "source_file": "meetings/19/chunks/15-11-2025_22-47-37__1__uuid.wav"
  },
  {
    "ts": "15-11-2025_22-48-08",
    "user_id": "1",
    "full_name": "John Doe",
    "role": "participant",
    "text": "Hôm nay chúng ta sẽ thảo luận về...",
    "source_file": "meetings/19/chunks/15-11-2025_22-48-08__1__uuid.wav"
  }
]
```

---

## ⚙️ How It Works

### **STT Job (enqueue_stt_job)**
1. Worker receives audio file path
2. Loads Whisper model (cached)
3. Transcribes audio to text
4. Creates entry object with timestamp, user info, and text
5. Appends to Redis cache (merges consecutive entries from same user within 30s)
6. Returns result

### **Merge Transcript Job (enqueue_merge_transcript_job)**
1. Fetches all transcripts from Redis cache
2. Creates DOCX document with header and meeting info
3. Adds each transcript entry as a paragraph
4. Saves DOCX to `meetings/{meeting_id}/final/`
5. Returns file path and metadata

---

## 💡 Key Features

✅ **Automatic STT Processing**
- Speech-to-Text happens automatically when audio is uploaded
- Worker processes jobs asynchronously

✅ **Smart Transcript Caching**
- Same user speaking within 30 seconds is merged into one entry
- Redis cache stores all transcripts for quick retrieval

✅ **Easy Document Generation**
- DOCX file created from cached transcripts
- Clean, organized format with timestamps and speaker info

✅ **Model Caching**
- Whisper model loaded once and reused
- Significantly faster subsequent transcriptions

---

## 🚀 Example Workflow

```bash
# Step 1: Start the Flask app and workers
python app.py  # Terminal 1
python worker.py  # Terminal 2

# Step 2: Upload first audio chunk
curl -X POST http://localhost:5000/api/stt_input \
  -F "file=@chunk1.wav" \
  -F "meeting_id=19" \
  -F "user_id=1" \
  -F "full_name=John Doe" \
  -F "role=speaker"

# Step 3: Upload more chunks (from same or different users)
curl -X POST http://localhost:5000/api/stt_input \
  -F "file=@chunk2.wav" \
  -F "meeting_id=19" \
  -F "user_id=2" \
  -F "full_name=Jane Smith" \
  -F "role=participant"

# Step 4: Wait for all STT jobs to complete (check job status if needed)

# Step 5: Create transcript document
curl -X POST http://localhost:5000/api/merge_transcript \
  -H "Content-Type: application/json" \
  -d '{"meeting_id": "19"}'

# Step 6: Check merge status and get download URL
curl http://localhost:5000/api/merge_transcript_status/job_id_here

# Step 7: Download the DOCX file
curl -O http://localhost:5000/api/transcript_file/19/transcript_19_15-11-2025_22-47-37.docx
```

---

## ⚠️ Important Notes

1. **Meeting ID must exist**: Folders will be created automatically
2. **Redis must be running**: Check `REDIS_URL` environment variable
3. **Whisper model**: First load takes time (~1-2 minutes for "base" model)
4. **Timestamp format**: Use `YYYY-MM-DD HH:MM:SS` for custom timestamps
5. **Same-user merging**: Transcripts within 30 seconds are automatically merged

---

## 🔍 Troubleshooting

**Problem:** No transcripts in DOCX file
- **Solution:** Check if STT jobs completed. View Redis cache: `redis-cli LRANGE meeting:19:transcripts 0 -1`

**Problem:** Worker not processing jobs
- **Solution:** Check if worker is running and connected to Redis

**Problem:** Whisper model fails to load
- **Solution:** Ensure `torch` and `openai-whisper` are installed. Check GPU availability.

**Problem:** File not found after upload
- **Solution:** Check if MEETINGS_DIR environment variable is set correctly
