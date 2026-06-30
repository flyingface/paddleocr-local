import os
from modelscope import snapshot_download

model_dir = "model_cache/official_models/PaddleOCR-VL-1.6"
print(f"Downloading model to {model_dir}...")

snapshot_download(
    "PaddlePaddle/PaddleOCR-VL-1.6",
    local_dir=model_dir
)

print("Download complete.")
