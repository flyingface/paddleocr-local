"""编排网关 - FastAPI 入口

职责: 接收 pandocr-web 请求,按 pipeline.yaml 规则调度子服务,拼装结果返回。
不持有任何业务数据,纯逻辑。
"""
import os
import time
import asyncio
import logging
from pathlib import Path
from typing import Optional, Dict, Any, List

import httpx
import yaml
from fastapi import FastAPI, File, UploadFile, HTTPException, Request
from fastapi.responses import JSONResponse
from prometheus_client import Counter, Histogram, generate_latest, CONTENT_TYPE_LATEST
from pydantic import BaseModel

# ---- 日志 ----
logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("preprocess.gateway")

# ---- Prometheus 指标 ----
REQUEST_COUNT = Counter(
    "preprocess_gateway_requests_total",
    "Gateway 请求总数",
    ["status"],
)
REQUEST_LATENCY = Histogram(
    "preprocess_gateway_request_duration_seconds",
    "Gateway 总时延(秒)",
    buckets=[0.05, 0.1, 0.2, 0.5, 1.0, 2.0, 5.0, 10.0],
)
STAGE_LATENCY = Histogram(
    "preprocess_gateway_stage_duration_seconds",
    "各 stage 时延(秒)",
    ["stage"],
    buckets=[0.01, 0.05, 0.1, 0.2, 0.5, 1.0, 2.0],
)
STAGE_SKIPPED = Counter(
    "preprocess_gateway_stage_skipped_total",
    "因服务不可用而跳过的 stage",
    ["stage", "reason"],
)

# ---- 配置 ----
PIPELINE_CONFIG_PATH = os.getenv("PIPELINE_CONFIG", "/app/config/pipeline.yaml")

# 子服务 URL
CORRECTION_URL = os.getenv("CORRECTION_URL", "http://paddleocr-preprocess-correction:8080")
CLASSIFY_URL = os.getenv("CLASSIFY_URL", "http://paddleocr-preprocess-classify:8080")
# OCR 服务 URL(可转发)
OCR_SERVICE_URL = os.getenv("OCR_SERVICE_URL", "http://pandocr-web:8000")

# HTTP 超时
SUB_SERVICE_TIMEOUT = float(os.getenv("SUB_SERVICE_TIMEOUT", "30"))

# ---- App ----
app = FastAPI(
    title="PaddleOCR 图像前置 - 编排网关",
    description="统一入口,串/并调度 quality/correction/classify 子服务",
    version="0.1.0",
)


def load_pipeline_config() -> dict:
    """加载编排规则"""
    path = Path(PIPELINE_CONFIG_PATH)
    if not path.exists():
        logger.warning("pipeline.yaml 不存在 (%s),使用空规则", path)
        return {"pipeline": []}
    try:
        with path.open("r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {"pipeline": []}
    except Exception as e:
        logger.error("解析 pipeline.yaml 失败: %s", e)
        return {"pipeline": []}


PIPELINE_CONFIG = load_pipeline_config()


# ---- 响应模型 ----
class HealthResponse(BaseModel):
    status: str
    services: Dict[str, str]
    pipeline_stages: int


class ServiceStatus(BaseModel):
    name: str
    url: str
    status: str  # up / down / unknown
    latency_ms: Optional[float] = None


# ---- 工具函数 ----
async def check_sub_service(url: str, timeout: float = 2.0) -> str:
    """检查子服务健康状态"""
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            r = await client.get(f"{url}/health")
            if r.status_code == 200:
                return "up"
            return "down"
    except Exception as e:
        logger.debug("子服务健康检查失败 %s: %s", url, e)
        return "down"


async def call_correction(file_bytes: bytes, filename: str) -> Optional[dict]:
    """调用矫正服务"""
    try:
        async with httpx.AsyncClient(timeout=SUB_SERVICE_TIMEOUT) as client:
            files = {"file": (filename, file_bytes)}
            r = await client.post(f"{CORRECTION_URL}/correct", files=files)
            r.raise_for_status()
            return r.json()
    except Exception as e:
        logger.warning("矫正服务调用失败: %s", e)
        return None


async def call_classify(file_bytes: bytes, filename: str) -> Optional[dict]:
    """调用分类服务(占位,等服务实现)"""
    try:
        async with httpx.AsyncClient(timeout=SUB_SERVICE_TIMEOUT) as client:
            files = {"file": (filename, file_bytes)}
            r = await client.post(f"{CLASSIFY_URL}/classify", files=files)
            r.raise_for_status()
            return r.json()
    except Exception as e:
        logger.warning("分类服务调用失败(可能未部署): %s", e)
        return None


def decide_ocr_route(classification: Optional[dict]) -> dict:
    """根据分类结果决定 OCR 路由

    当前是简单规则:有分类就用分类,否则 fallback 到 pp-ocrv6
    """
    if not classification or "label" not in classification:
        return {"service": "pp-ocrv6", "mode": "general", "reason": "no_classification"}

    label = classification["label"]
    confidence = classification.get("confidence", 0.0)

    # L1 分类到 OCR 路由的映射
    routing_table = {
        "id_card": {"service": "pp-ocrv6", "mode": "structured_card"},
        "passport": {"service": "pp-ocrv6", "mode": "structured_card"},
        "driving_license": {"service": "pp-ocrv6", "mode": "structured_card"},
        "bank_card": {"service": "pp-ocrv6", "mode": "structured_card"},
        "invoice": {"service": "paddleocr-vl-api", "mode": "layout_parsing"},
        "receipt": {"service": "paddleocr-vl-api", "mode": "layout_parsing"},
        "contract": {"service": "paddleocr-vl-api", "mode": "layout_parsing"},
        "report": {"service": "paddleocr-vl-api", "mode": "layout_parsing"},
        "menu": {"service": "pp-ocrv6", "mode": "menu_translate"},
        "handwriting": {"service": "paddleocr-vl-api", "mode": "layout_parsing"},
    }

    route = routing_table.get(label, {"service": "pp-ocrv6", "mode": "general"})
    route["reason"] = f"classified_as_{label}_conf_{confidence:.2f}"
    return route


# ---- 接口 ----
@app.get("/health", response_model=HealthResponse)
async def health():
    """健康检查 + 子服务状态汇总"""
    correction_status = await check_sub_service(CORRECTION_URL)
    classify_status = await check_sub_service(CLASSIFY_URL)

    services = {
        "correction": correction_status,
        "classify": classify_status,
    }
    overall = "ok" if any(s == "up" for s in services.values()) else "degraded"

    return {
        "status": overall,
        "services": services,
        "pipeline_stages": len(PIPELINE_CONFIG.get("pipeline", [])),
    }


@app.get("/services")
async def list_services():
    """列出所有子服务状态(详细)"""
    results = []
    for name, url in [("correction", CORRECTION_URL), ("classify", CLASSIFY_URL)]:
        start = time.time()
        status = await check_sub_service(url)
        latency = (time.time() - start) * 1000
        results.append({
            "name": name,
            "url": url,
            "status": status,
            "latency_ms": round(latency, 2) if status == "up" else None,
        })
    return results


@app.get("/config/pipeline")
async def get_pipeline_config():
    """查看编排规则"""
    return PIPELINE_CONFIG


@app.put("/config/pipeline")
async def update_pipeline_config(config: dict):
    """热更新编排规则(开发期用)"""
    global PIPELINE_CONFIG
    try:
        # 验证 YAML 可序列化
        yaml.safe_dump(config)
        PIPELINE_CONFIG = config
        logger.info("编排规则已热更新")
        return {"status": "ok", "stages": len(config.get("pipeline", []))}
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"配置格式错误: {e}")


@app.get("/metrics")
async def metrics():
    """Prometheus 指标"""
    return JSONResponse(
        content=generate_latest().decode("utf-8").split("\n"),
        media_type=CONTENT_TYPE_LATEST,
    )


@app.post("/pipeline")
async def pipeline(
    request: Request,
    file: UploadFile = File(...),
):
    """主入口:对一张图走完整 pipeline

    返回:
    - processed_file_b64: 矫正后图像(若做了矫正)
    - stage_results: 各 stage 详细结果
    - suggested_ocr: 路由建议
    """
    start = time.time()
    file_bytes = await file.read()
    filename = file.filename or "image.jpg"

    stage_results: Dict[str, Any] = {}
    current_file = file_bytes

    try:
        # 遍历 pipeline 配置
        for stage_def in PIPELINE_CONFIG.get("pipeline", []):
            stage = stage_def.get("stage")
            on_missing = stage_def.get("on_missing", "skip")
            condition = stage_def.get("condition", "")
            service_url = stage_def.get("service", "")
            timeout = stage_def.get("timeout_ms", SUB_SERVICE_TIMEOUT * 1000) / 1000

            # 条件判断(简单支持 ==)
            if condition and not _eval_condition(condition, stage_results):
                logger.debug("stage %s 条件不满足,跳过", stage)
                continue

            stage_start = time.time()
            try:
                if stage == "correction":
                    result = await asyncio.wait_for(
                        call_correction(current_file, filename),
                        timeout=timeout,
                    )
                    if result is None:
                        stage_results[stage] = {"skipped": True, "reason": "service_unavailable"}
                        STAGE_SKIPPED.labels(stage=stage, reason="unavailable").inc()
                        if on_missing == "error":
                            raise HTTPException(status_code=502, detail=f"矫正服务不可用")
                    else:
                        stage_results[stage] = {
                            "applied": result.get("applied"),
                            "confidence": result.get("confidence"),
                            "corner_points": result.get("corner_points"),
                        }
                        # 如果矫正了,后续 stage 用矫正后图像
                        if result.get("applied"):
                            import base64
                            current_file = base64.b64decode(result["corrected_image_b64"])

                elif stage == "classify":
                    result = await asyncio.wait_for(
                        call_classify(current_file, filename),
                        timeout=timeout,
                    )
                    if result is None:
                        stage_results[stage] = {"skipped": True, "reason": "service_unavailable"}
                        STAGE_SKIPPED.labels(stage=stage, reason="unavailable").inc()
                    else:
                        stage_results[stage] = {
                            "label": result.get("label"),
                            "confidence": result.get("confidence"),
                            "top3": result.get("top3", []),
                        }

                elif stage == "route":
                    # 路由决策(纯逻辑,不计费时延)
                    classification = stage_results.get("classify")
                    route = decide_ocr_route(classification)
                    stage_results[stage] = route

                else:
                    logger.warning("未知 stage: %s,跳过", stage)
                    continue

            except asyncio.TimeoutError:
                stage_results[stage] = {"skipped": True, "reason": "timeout"}
                STAGE_SKIPPED.labels(stage=stage, reason="timeout").inc()
                if on_missing == "error":
                    raise HTTPException(status_code=504, detail=f"stage {stage} 超时")
            except Exception as e:
                logger.exception("stage %s 异常: %s", stage, e)
                stage_results[stage] = {"skipped": True, "reason": f"exception: {str(e)[:100]}"}
                if on_missing == "error":
                    raise HTTPException(status_code=500, detail=f"stage {stage} 失败")

            STAGE_LATENCY.labels(stage=stage).observe(time.time() - stage_start)

        # 拼最终响应
        route = stage_results.get("route", {"service": "pp-ocrv6", "mode": "general"})

        # 把 current_file 编码回 base64(如果矫正过)
        import base64
        if current_file != file_bytes:
            processed_b64 = base64.b64encode(current_file).decode("utf-8")
        else:
            processed_b64 = base64.b64encode(file_bytes).decode("utf-8")

        total_latency = (time.time() - start) * 1000
        REQUEST_LATENCY.observe(time.time() - start)
        REQUEST_COUNT.labels(status="ok").inc()

        return {
            "request_id": request.headers.get("X-Request-Id", ""),
            "processed_file_b64": processed_b64,
            "stage_results": stage_results,
            "suggested_ocr": route,
            "total_latency_ms": round(total_latency, 2),
        }

    except HTTPException:
        REQUEST_COUNT.labels(status="error").inc()
        raise
    except Exception as e:
        REQUEST_COUNT.labels(status="error").inc()
        logger.exception("pipeline 异常: %s", e)
        raise HTTPException(status_code=500, detail=f"pipeline 失败: {str(e)}")


def _eval_condition(condition: str, context: dict) -> bool:
    """极简条件求值(只支持 == 和 and/or)

    例: "quality.needs_correction == true"
    """
    # 安全:用受限的 eval
    try:
        # 只允许简单属性访问
        safe_globals = {"__builtins__": {}}
        safe_locals = context
        return bool(eval(condition, safe_globals, safe_locals))
    except Exception:
        return True  # 求值失败默认通过


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app:app",
        host=os.getenv("HOST", "0.0.0.0"),
        port=int(os.getenv("PORT", "8080")),
        log_level=os.getenv("LOG_LEVEL", "info").lower(),
    )
