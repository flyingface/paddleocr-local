# 矫正服务 Dockerfile
# 基于 NVIDIA CUDA 12.6 + Python 3.11
#
# 构建: docker build -t paddleocr-preprocess-correction .
# 运行: docker run --gpus all -p 8084:8080 \
#         -v /path/to/models:/models \
#         -e CORRECTION_MODEL_PATH=/models/cv_resnet18_card_correction.onnx \
#         paddleocr-preprocess-correction

FROM nvidia/cuda:12.6.3-cudnn-runtime-ubuntu22.04

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# 基础工具
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3.11 python3.11-venv python3-pip \
    libgl1 libglib2.0-0 \
    curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# 装依赖(单独成层,缓存友好)
COPY requirements.txt .
RUN pip install --upgrade pip && \
    pip install -r requirements.txt

# 代码
COPY app.py inference.py ./

# 暴露端口
EXPOSE 8080

# 健康检查
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD curl -f http://localhost:8080/health || exit 1

CMD ["python", "-m", "uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8080"]
