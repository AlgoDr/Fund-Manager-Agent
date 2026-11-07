import urllib.request

url = "https://github.com/snakers4/silero-vad/raw/v4.0/files/silero_vad.onnx"
dest = "/Users/deepakrathore/Documents/Assingments/FUND_MANAGER_VOICE_AI/models/static/silero_vad.onnx"

print("Downloading uncorrupted Silero VAD binary model...")
try:
    urllib.request.urlretrieve(url, dest)
    print("Download completed successfully!")
except Exception as e:
    print(f"Error downloading file: {e}")
