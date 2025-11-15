# Audio Merge Implementation - Changes Summary

## Problem Solved
- Merge job được queued nhưng không chạy ngay, không trả lại file
- FFmpeg concat lỗi với Opus codec ("opus codec not supported in WAVE format")
- File merge không được tạo ra
- Log không ghi lỗi đầy đủ

## Solutions Implemented

### 1. **Synchronous Merge Execution** (`app.py`)
- Thay vì put job vào queue (async), giờ merge chạy **ngay khi request** (synchronous)
- Response trả về status "success" hoặc "error" với full details
- Client nhận được đường dẫn file merged ngay lập tức

### 2. **New Merge Function** (`utils.py`)
- Thêm hàm `merge_audio_chunks_direct()` sử dụng **PyDub** thay vì FFmpeg concat
- Hỗ trợ tất cả định dạng: `.wav`, `.ogg`, `.mp3`, `.m4a`, `.flac`, `.opus`
- Tự động normalize audio format trước khi ghép:
  - Đồng bộ sample rate
  - Đồng bộ số channels
- **Xuất trực tiếp sang OGG format** (nén âm thanh)
- Ghi log chi tiết mỗi bước xử lý

### 3. **Improved Error Handling** (`jobs.py`)
- Tất cả lỗi ghi vào `merge.log` với full traceback
- Output chỉ là file OGG (không tạo WAV tạm thời)
- Tự động xóa các file OGG cũ trước khi merge mới
- Log chi tiết: số file, duration, file size

### 4. **New Download Endpoint** (`app.py`)
- Endpoint `/api/merged_file/<meeting_id>/<filename>` để download file OGG đã merge

## API Usage

### Merge Audio Files (Synchronous)
```bash
POST /api/merge_audio
Content-Type: application/json

{
  "meeting_id": "19"
}

# Response (success):
{
  "status": "success",
  "meeting_id": "19",
  "merged_file": "meetings/19/final/merged_15-11-2025_23-47-08.ogg",
  "url": "http://localhost:5000/api/merged_file/19/merged_15-11-2025_23-47-08.ogg"
}

# Response (error):
{
  "status": "error",
  "meeting_id": "19",
  "error": "No audio chunks found"
}
```

### Download Merged File
```bash
GET /api/merged_file/19/merged_15-11-2025_23-47-08.ogg
```

## File Output

**Before:** Tạo WAV → chuyển sang OGG → xóa WAV  
**After:** Merge tất cả files → xuất trực tiếp OGG  
**Result:** File OGG nén được lưu tại `meetings/{meeting_id}/final/merged_<timestamp>.ogg`

## Log Output Example

```
=== Merge started at 2025-11-15 23:47:08.123456 ===
Meeting ID: 19
Chunks dir: meetings/19/chunks
Final dir: meetings/19/final
Output OGG file: meetings/19/final/merged_15-11-2025_23-47-08.ogg
Deleted old OGG file: merged_15-11-2025_23-45-00.ogg
Total deleted old OGG files: 1/1
Starting audio merge with direct format conversion...
Found 4 audio files to merge
Processing 1/4: 15-11-2025_22-47-37__1__757b5c3e758641b9889e956c8d9bbce5.wav
  -> Initialized with 5.23s (1ch, 48000Hz)
Processing 2/4: 15-11-2025_22-48-08__1__6e1cbb719c5445c1887458d59439163c.wav
  -> Added 4.87s, total now: 10.10s
...
Successfully merged 4/4 files
Total duration: 24.56 seconds

Exporting to OGG format: meetings/19/final/merged_15-11-2025_23-47-08.ogg
OGG export completed successfully!
Output file size: 1.23 MB
Merge and OGG conversion completed successfully!
Merged OGG file: meetings/19/final/merged_15-11-2025_23-47-08.ogg
=== Merge ended at 2025-11-15 23:47:10.456789 ===
```

## Technical Details

### PyDub Advantages
- Không cần FFmpeg concat (avoid opus issues)
- Tự động detect input format
- Hỗ trợ re-encoding quality tuning
- Exception handling tốt hơn

### Format Normalization
- Sample Rate: Tất cả convert về sample rate của file đầu tiên
- Channels: Tất cả convert về channel count của file đầu tiên
- Codec: Tất cả convert sang Vorbis (OGG format)

### OGG Export Settings
- Format: OGG (Vorbis codec)
- Bitrate: 128k (quality tuning)
- Quality: 7/10 (codec-specific quality setting)
- Result: ~50-75MB/hour audio (high quality)

## Dependencies Required

```
pydub>=0.25.1
ffmpeg (system dependency - for pydub decoding)
```

## Testing

```bash
# Test merge
curl -X POST http://localhost:5000/api/merge_audio \
  -H "Content-Type: application/json" \
  -d '{"meeting_id": "19"}'

# Check log
cat meetings/19/merge.log
```

