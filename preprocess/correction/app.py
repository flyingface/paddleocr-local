"""矫正服务 - FastAPI 入口

提供三个接口:
- POST /correct: 单图矫正
- GET  /health: 健康检查
- GET  /metrics: Prometheus 指标
"""
import os
import time
import base64
import logging
from typing import Optional

import numpy as np
import cv2
from fastapi import FastAPI, File, UploadFile, HTTPException
from fastapi.responses import JSONResponse
from prometheus_client import Counter, Histogram, generate_latest, CONTENT_TYPE_LATEST
from pydantic import BaseModel

from inference import CorrectionEngine

# ---- 日志 ----
logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("preprocess.correction.api")

# ---- Prometheus 指标 ----
REQUEST_COUNT = Counter(
    "preprocess_correction_requests_total",
    "矫正请求总数",
    ["status"],
)
REQUEST_LATENCY = Histogram(
    "preprocess_correction_request_duration_seconds",
    "矫正请求时延(秒)",
    buckets=[0.01, 0.05, 0.1, 0.2, 0.5, 1.0, 2.0, 5.0],
)
INFERENCE_LATENCY = Histogram(
    "preprocess_correction_inference_duration_seconds",
    "纯推理时延(秒)",
    buckets=[0.005, 0.01, 0.05, 0.1, 0.5, 1.0],
)

# ---- App ----
app = FastAPI(
    title="PaddleOCR 图像前置 - 矫正服务",
    description="基于 cv_resnet18_card_correction 的几何矫正",
    version="0.1.0",
)

# 模型延迟加载,启动时再加载
_engine: Optional[CorrectionEngine] = None


@app.on_event("startup")
async def load_model():
    """启动时加载模型,失败则服务起不来"""
    global _engine
    try:
        _engine = CorrectionEngine()
        logger.info("矫正服务就绪")
    except FileNotFoundError as e:
        logger.error("模型加载失败: %s", e)
        # 不 raise,允许服务启动,health 报 unhealthy
        _engine = None
    except Exception as e:
        logger.exception("模型加载异常: %s", e)
        _engine = None


# ---- 响应模型 ----
class CorrectResponse(BaseModel):
    corrected_image_b64: str
    applied: bool
    confidence: float
    corner_points: list
    latency_ms: float


class HealthResponse(BaseModel):
    status: str
    model_loaded: bool
    providers: Optional[list] = None


# ---- 接口 ----
@app.get("/health", response_model=HealthResponse)
async def health():
    """健康检查"""
    if _engine is None:
        return JSONResponse(
            status_code=503,
            content={"status": "unhealthy", "model_loaded": False},
        )
    return {
        "status": "ok",
        "model_loaded": True,
        "providers": _engine.session.get_providers(),
    }


@app.get("/metrics")
async def metrics():
    """Prometheus 指标"""
    return JSONResponse(
        content=generate_latest().decode("utf-8").split("\n"),
        media_type=CONTENT_TYPE_LATEST,
    )


@app.post("/correct", response_model=CorrectResponse)
async def correct(file: UploadFile = File(...)):
    """对上传的图像做矫正

    支持格式: jpg / png / webp
    """
    if _engine is None:
        REQUEST_COUNT.labels(status="model_not_loaded").inc()
        raise HTTPException(status_code=503, detail="模型未加载")

    start = time.time()
    try:
        # 1. 读图
        contents = await file.read()
        nparr = np.frombuffer(contents, np.uint8)
        image = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        if image is None:
            REQUEST_COUNT.labels(status="decode_error").inc()
            raise HTTPException(status_code=400, detail="无法解码图像")

        # 2. 推理
        inference_start = time.time()
        result = _engine.correct(image)
        INFERENCE_LATENCY.observe(time.time() - inference_start)

        # 3. 编码回 base64
        corrected = result["corrected_image"]
        encode_params = [cv2.IMWRITE_JPEG_QUALITY, 90]
        ok, buf = cv2.imencode(".jpg", corrected, encode_params)
        if not ok:
            REQUEST_COUNT.labels(status="encode_error").inc()
            raise HTTPException(status_code=500, detail="编码矫正后图像失败")

        b64 = base64.b64encode(buf.tobytes()).decode("utf-8")

        latency_ms = (time.time() - start) * 1000
        REQUEST_LATENCY.observe(time.time() - start)
        REQUEST_COUNT.labels(status="ok").inc()

        logger.info(
            "矫正完成 applied=%s confidence=%.3f latency=%.1fms",
            result["applied"],
            result["confidence"],
            latency_ms,
        )

        return CorrectResponse(
            corrected_image_b64=b64,
            applied=result["applied"],
            confidence=result["confidence"],
            corner_points=result["corner_points"],
            latency_ms=latency_ms,
        )

    except HTTPException:
        raise
    except Exception as e:
        REQUEST_COUNT.labels(status="error").inc()
        logger.exception("矫正异常: %s", e)
        raise HTTPException(status_code=500, detail=f"矫正失败: {str(e)}")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app:app",
        host=os.getenv("HOST", "0.0.0.0"),
        port=int(os.getenv("PORT", "8080")),
        log_level=os.getenv("LOG_LEVEL", "info").lower(),
    )
