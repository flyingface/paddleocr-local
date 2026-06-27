# Gateway Dockerfile
# 纯逻辑服务,不需要 GPU
#
# 构建: docker build -t paddleocr-preprocess-gateway .
# 运行: docker run -p 8087:8080 \
#         -e CORRECTION_URL=http://host:8084 \
#         -e CLASSIFY_URL=http://host:8085 \
#         paddleocr-preprocess-gateway

FROM python:3.11-slim

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# 装依赖
COPY requirements.txt .
RUN pip install --upgrade pip && \
    pip install -r requirements.txt

# 代码
COPY app.py ./

# 配置目录
RUN mkdir -p /app/config
COPY config/ /app/config/

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import httpx; httpx.get('http://localhost:8080/health', timeout=2)" || exit 1

CMD ["python", "-m", "uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8080"]
