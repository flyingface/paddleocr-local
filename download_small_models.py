import os
import requests
import tarfile
import urllib.request
from pathlib import Path

def download_and_extract(url, extract_to):
    print(f"Downloading {url} to {extract_to}...")
    Path(extract_to).mkdir(parents=True, exist_ok=True)
    tar_path = Path(extract_to) / "model.tar"
    urllib.request.urlretrieve(url, tar_path)
    
    print(f"Extracting {tar_path}...")
    with tarfile.open(tar_path) as tar:
        tar.extractall(path=extract_to)
    
    tar_path.unlink()
    print("Done.")

# Download the small preprocessor models
models = [
    ("https://paddle-model-ecology.bj.bcebos.com/paddlex/official_inference_model/paddle3.0.0/PP-LCNet_x1_0_doc_ori_infer.tar", "model_cache/official_models/PP-LCNet_x1_0_doc_ori"),
    ("https://paddle-model-ecology.bj.bcebos.com/paddlex/official_inference_model/paddle3.0.0/UVDoc_infer.tar", "model_cache/official_models/UVDoc"),
    ("https://paddle-model-ecology.bj.bcebos.com/paddlex/official_inference_model/paddle3.0.0/PP-DocLayoutV3_infer.tar", "model_cache/official_models/PP-DocLayoutV3")
]

for url, extract_to in models:
    download_and_extract(url, extract_to)
