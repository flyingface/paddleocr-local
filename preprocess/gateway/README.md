# 编排网关 (Preprocess Gateway)

> 纯逻辑的编排服务,负责:接收 pandocr-web 请求 → 调度子服务(质量/矫正/分类) → 拼装结果 → 返回。

## 状态

🚧 **骨架阶段**

## 接口

主接口:

```http
POST /pipeline
Content-Type: multipart/form-data
X-Request-Id: <uuid>

file: <image or PDF>
```

返回: 参见 `../README.md` 的"上游 / 下游契约"。

管理接口:

- `GET /health` — 健康检查
- `GET /services` — 列出子服务状态
- `GET /metrics` — Prometheus 指标
- `GET /config/pipeline` — 查看编排规则
- `PUT /config/pipeline` — 热更新编排规则

## 编排规则 (config/pipeline.yaml)

```yaml
pipeline:
  - stage: correction
    service: http://paddleocr-preprocess-correction:8080
    on_missing: skip
  - stage: classify
    service: http://paddleocr-preprocess-classify:8080
    on_missing: skip
  - stage: route
    type: ocr_router
    default_ocr: pp-ocrv6
    rules:
      - if: "classification.label in ['id_card', 'passport']"
        then: {service: pp-ocrv6, mode: structured}
```

## 待办

- [ ] 实现 `app.py` FastAPI 入口
- [ ] 实现编排引擎(读 YAML → 串/并执行子服务 → 拼结果)
- [ ] 实现子服务健康检查 + 降级逻辑
- [ ] 在 `docker-compose.yml` 中注册服务
- [ ] 接入 pandocr-web(改 `server.py` 30 行)
