# 图像前置层 - 详细架构

## 一、设计目标

把 OCR 之前的"脏活"全部收编到独立的微服务集群中,实现:

1. **可插拔**:任意服务挂了不影响主流程
2. **可观测**:全链路 Prometheus 指标
3. **可路由**:根据分类结果自动选择最合适的 OCR 服务
4. **可演进**:pipeline.yaml 决定编排规则,改规则不动代码

## 二、为什么是 Gateway + 子服务 而不是 单体

### 单体的代价

把所有模型塞进一个容器:
- ❌ 镜像爆炸(几个模型加起来 5GB+)
- ❌ 任意一个模型升级需要重建整个镜像
- ❌ GPU 资源无法按模型粒度调度
- ❌ 故障域耦合:一个崩,全崩

### 微服务的收益

- ✅ 每个服务独立扩缩容
- ✅ 模型升级 = 重建一个镜像
- ✅ GPU 按需分配(矫正用轻量卡,分类可用大卡)
- ✅ 故障隔离:矫正挂了,分类和路由还能跑

### 代价:复杂度上升

- ➕ 需要服务发现 / 健康检查 / 重试 / 降级
- ➕ 跨服务时延(每跳 +5-20ms)
- ➕ 部署变多

**结论**:值得。OCR 本身延迟在 500ms-5s 级别,几十 ms 的编排开销可忽略。

## 三、数据流

```
[输入] 1 张图 或 1 个 PDF 页
   │
   ▼
[质量评估] (可选,80ms CPU)
   │  score, needs_correction
   ▼
[矫正]  (条件: needs_correction == true)
   │  矫正后图像, corner_points
   ▼
[分类]  (始终跑,30ms GPU)
   │  label, confidence, top3
   ▼
[路由决策]  (纯逻辑,<1ms)
   │  选 OCR 服务 + 模式
   ▼
[OCR 推理]  (走 pandocr-web 已有逻辑)
   │
   ▼
[返回]  原 OCR 结果 + 全链路 stage_results
```

## 四、关键设计决策

### 4.1 Gateway 必须是无状态的

- 不存任何业务数据
- pipeline.yaml 走 ConfigMap(本地) / Volume(K8s)
- 多副本可任意水平扩展

### 4.2 服务发现方式

- **开发**:走 docker-compose 服务名(如 `http://paddleocr-preprocess-correction:8080`)
- **生产**:走 K8s Service DNS(如 `http://paddleocr-preprocess-correction.paddleocr.svc.cluster.local:8080`)
- **不**用 Consul / Nacos:本项目规模不值得

### 4.3 失败降级策略

| 阶段 | 失败时 |
|---|---|
| 质量评估 | skip,直接走矫正 |
| 矫正 | skip,直接走分类(用原图) |
| 分类 | skip,走 default OCR 路由 |
| Gateway 自身 | pandocr-web 检测到,降级到无预处理模式 |

### 4.4 时延预算

| 阶段 | 预算 | 实测 |
|---|---|---|
| Gateway 调度开销 | < 20ms | 待测 |
| 质量评估 | 80ms (CPU) / 20ms (GPU) | 待测 |
| 矫正 | 60ms (GPU) | 待测 |
| 分类 | 30ms (GPU) | 待测 |
| **小计** | **< 200ms** | 待测 |

OCR 本身通常 500ms-5s,**预处理 200ms 是可接受预算**。

## 五、安全

1. **API Token** — pandocr-web 调用 Gateway 时带 Token,Gateway 再透传给子服务
2. **不要暴露子服务到外网** — 它们只走 docker network
3. **上传文件大小限制** — 复用 pandocr-web 的 `PANDOCR_MAX_UPLOAD_MB`
4. **文件类型校验** — 只接 image/jpeg, image/png, application/pdf

## 六、监控

### 关键指标

```
# 流量
preprocess_requests_total{service, status}
preprocess_request_duration_seconds{service, stage}

# 业务
preprocess_correction_applied_total{trigger_reason}
preprocess_classification_confidence_histogram
preprocess_ocr_route_decisions_total{from, to}

# 资源
preprocess_gpu_memory_bytes{service}
preprocess_model_load_duration_seconds{service}
```

### 关键告警

- 矫正服务 P99 > 200ms
- 分类置信度 < 0.5 占比 > 20% (可能模型漂移)
- 任一服务连续 3 次健康检查失败

## 七、演进路径

```
v0.x  矫正 + 分类(L1 10 类)
v1.x  字段抽取模板(按分类路由)
v2.x  智能路由(LLM 决策)
v3.x  端侧 ONNX(支持 Rokid 眼镜)
```

---

_详细问题请看每个子服务的 README。_
