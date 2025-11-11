import whisper

# Tải mô hình
model = whisper.load_model("medium")

# In ra thông tin mô hình
print("Model loaded successfully:", model.dims)
