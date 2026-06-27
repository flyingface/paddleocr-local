"""矫正服务 - 基础 API 测试

运行:
    pip install pytest httpx
    pytest tests/test_api.py -v
"""
import pytest
from fastapi.testclient import TestClient

from app import app

client = TestClient(app)


def test_health():
    """健康检查接口"""
    r = client.get("/health")
    # 模型可能没加载(测试环境没放模型),但接口本身要响应
    assert r.status_code in (200, 503)
    data = r.json()
    assert "status" in data
    assert "model_loaded" in data


def test_metrics():
    """Prometheus 指标接口"""
    r = client.get("/metrics")
    assert r.status_code == 200
    # 至少有 HELP/TYPE 元数据
    assert "preprocess_correction" in r.text or "HELP" in r.text


def test_correct_no_model():
    """没模型时调用应该 503 而不是 500"""
    # 不放测试图,只确认接口结构
    r = client.post("/correct")
    # 没有文件应该 422
    assert r.status_code in (422, 503)


def test_correct_with_invalid_file():
    """传一个非图像文件应该 400"""
    r = client.post(
        "/correct",
        files={"file": ("test.txt", b"not an image", "text/plain")},
    )
    # 模型未加载 -> 503;  解码失败 -> 400
    assert r.status_code in (400, 503)
