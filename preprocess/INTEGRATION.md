# 集成指南 - paddleocr-local 接入图像前置层

> 本文档说明:如何把 `preprocess/` 层接入到现有 `pandocr-web` 中。

## 一、整体改动

| 文件 | 改动量 | 性质 |
|---|---|---|
| `server.py` | +30 行 | 可选启用,通过环境变量开关 |
| `docker-compose.yml` | +3 个 service | 新增,不破坏现有服务 |
| `preprocess/` | 全部新增 | 独立目录 |

**核心承诺**:原有 `pandocr-web` 的所有 API 接口**100% 保持兼容**。启用预处理是**可选的,渐进式**的。

## 二、接入步骤

### Step 1:复制 preprocess/ 目录(已完成)

```bash
# 如果是从 patch 应用的,目录已在仓库内
ls preprocess/
#  ARCHITECTURE.md  README.md  classify/  correction/  gateway/
```

### Step 2:挂载 preprocess 服务到 docker-compose.yml

把以下 4 个 service 块加到现有 `docker-compose.yml` 的 `services:` 下(在任何 `pandocr-web` 之前):

```yaml
  # 矫正服务
  paddleocr-preprocess-correction:
    build: ./preprocess/correction
    container_name: paddleocr-preprocess-correction
    ports:
      - "127.0.0.1:8084:8080"
    environment:
      - CORRECTION_MODEL_PATH=/models/cv_resnet18_card_correction.onnx
      - LOG_LEVEL=INFO
    volumes:
      - ./preprocess_models/correction:/models
    networks:
      - paddleocr-network

  # 分类服务(占位,等 PaddleClas 训练完成后实现)
  paddleocr-preprocess-classify:
    build: ./preprocess/classify
    container_name: paddleocr-preprocess-classify
    profiles: ["classify"]   # 默认不启动,需要时 --profile classify
    ports:
      - "127.0.0.1:8085:8080"
    networks:
      - paddleocr-network

  # 编排网关
  paddleocr-preprocess-gateway:
    build: ./preprocess/gateway
    container_name: paddleocr-preprocess-gateway
    ports:
      - "127.0.0.1:8087:8080"
    environment:
      - CORRECTION_URL=http://paddleocr-preprocess-correction:8080
      - CLASSIFY_URL=http://paddleocr-preprocess-classify:8080
      - PIPELINE_CONFIG=/app/config/pipeline.yaml
    volumes:
      - ./preprocess/gateway/config:/app/config
    networks:
      - paddleocr-network

  # pandocr-web 改造:加环境变量
  pandocr-web:
    # ... 原有配置 ...
    environment:
      # ... 原有 env ...
      - PREPROCESS_GATEWAY_URL=http://paddleocr-preprocess-gateway:8087
      - PREPROCESS_ENABLED=1   # 0 关闭, 1 开启
```

### Step 3:改造 `server.py`(关键)

**改动 1:顶部加环境变量(约 10 行)**

```python
# 在 server.py 顶部常量区加
PREPROCESS_GATEWAY_URL = os.getenv("PREPROCESS_GATEWAY_URL", "").strip()
PREPROCESS_ENABLED = parse_bool_env("PREPROCESS_ENABLED", "0")
PREPROCESS_TIMEOUT = float(os.getenv("PREPROCESS_TIMEOUT", "60"))
```

**改动 2:加预处理调用函数(约 20 行)**

```python
# 在 helper 区加
async def call_preprocess_gateway(file_bytes: bytes, filename: str) -> Optional[dict]:
    """调用 Gateway 预处理(可选)"""
    if not PREPROCESS_ENABLED or not PREPROCESS_GATEWAY_URL:
        return None
    try:
        async with httpx.AsyncClient(timeout=PREPROCESS_TIMEOUT) as client:
            files = {"file": (filename, file_bytes)}
            r = await client.post(
                f"{PREPROCESS_GATEWAY_URL}/pipeline",
                files=files,
            )
            r.raise_for_status()
            return r.json()
    except Exception as e:
        logger.warning("预处理 Gateway 调用失败(降级到无预处理): %s", e)
        return None
```

**改动 3:在 /api/paddleocr-vl-1.6 入口前加一行**

```python
# 在 /api/paddleocr-vl-1.6 路由里,读 file 之后、转 base64 之前:
@app.post("/api/paddleocr-vl-1.6")
async def paddleocr_vl_1_6(request: Request, file: UploadFile = File(...)):
    file_bytes = await file.read()

    # 【新增】预处理
    preprocess_result = await call_preprocess_gateway(file_bytes, file.filename or "image.jpg")
    if preprocess_result and "processed_file_b64" in preprocess_result:
        file_bytes = base64.b64decode(preprocess_result["processed_file_b64"])
        # 把 stage_results 放进响应(可选,见下一步)

    # ... 原有逻辑不变 ...
```

**改动 4:可选 - 在响应里加 stage_results**

```python
    return {
        "result": ...,  # 原有
        "preprocess": preprocess_result.get("stage_results", {}) if preprocess_result else None,
    }
```

**改动 5:/api/pp-ocrv6 同上(可选)**

同样在入口加一行,逻辑一致。

## 三、验证流程

### 1. 起矫正服务

```bash
# 1) 放模型(暂时用占位)
mkdir -p preprocess_models/correction
touch preprocess_models/correction/cv_resnet18_card_correction.onnx

# 2) build + up
docker compose --env-file env.docker build paddleocr-preprocess-correction
docker compose --env-file env.docker up -d --no-start
docker compose --env-file env.docker start paddleocr-preprocess-correction

# 3) 健康检查
curl http://localhost:8084/health
# 预期: {"status":"unhealthy","model_loaded":false}  (因为模型文件是占位)
```

### 2. 起 Gateway

```bash
docker compose --env-file env.docker build paddleocr-preprocess-gateway
docker compose --env-file env.docker up -d --no-start
docker compose --env-file env.docker start paddleocr-preprocess-gateway

curl http://localhost:8087/health
# 预期: services.correction="down"（因为模型没真）, services.classify="down"（没启）
# status: "degraded"
```

### 3. 端到端测试(可选)

```bash
# 上传一张图
curl -X POST -F "file=@test.jpg" http://localhost:8087/pipeline
# 预期: 200 OK,stage_results.correction.skipped=true,stage_results.route.service=pp-ocrv6
```

### 4. 接入 pandocr-web

```bash
# 设环境变量开启预处理
export PREPROCESS_ENABLED=1
export PREPROCESS_GATEWAY_URL=http://localhost:8087

# 重启 pandocr-web
docker compose --env-file env.docker restart pandocr-web

# 走原 web 接口
curl -X POST -F "file=@test.jpg" http://localhost:8000/api/paddleocr-vl-1.6
# 响应里会多出 "preprocess" 字段
```

## 四、降级策略

| 场景 | 行为 |
|---|---|
| Gateway 不可达 | pandocr-web 捕获异常,**降级到无预处理**,只记录 warning |
| 矫正服务挂了 | Gateway skip 该 stage,继续走 |
| 分类服务没启 | Gateway skip,该 stage 标 skipped |
| 路由决策失败 | 用 default_ocr:`pp-ocrv6` + `general` 模式 |

**总原则**:任何预处理失败,都**不能**让原 OCR 流程崩。`PREPROCESS_ENABLED=0` 是**绝对安全开关**。

## 五、Roadmap

- [x] **v0.1**:骨架 + 文档(今晚交付)
- [x] **v0.2**:矫正服务 + Gateway 代码(今晚交付)
- [x] **v0.3**:pandocr-web 接入 patch(本文档)
- [ ] **v0.4**:评测集 + 矫正前后对比报告(下一阶段)
- [ ] **v1.0**:分类服务实现(下一阶段)
- [ ] **v1.1**:字段抽取模板
- [ ] **v1.2**:Prometheus + Grafana
- [ ] **v2.0**:K8s Helm Chart

---

_本指南是渐进式接入,所有变更都是可逆的。_ 🧊
