# 图像前置预处理层 (Preprocess Layer)

> 在 PaddleOCR 推理前的一道「图像清洗 + 业务理解」中枢。
> 让 OCR 不再裸跑,先看清楚再动手。

## 一、为什么需要这一层

PaddleOCR-VL / PP-OCRv6 / Unlimited-OCR 都假设输入是**「干净印刷件」**。现实里:

- 📷 拍照件有透视、有阴影、有反光
- 🆔 卡证件需要先矫正到正矩形,字段才能对齐
- 🧾 票据 / 合同 / 名片需要先知道「这是哪类文档」,才能选对字段模板
- 👓 眼镜 / 手机拍的第一视角几乎都带透视

**前置层的目标**:把"OCR 之前的不确定性"全部消化掉,让下游 OCR 服务只做最擅长的事。

## 二、架构总览

```
┌─────────────┐
│   Browser   │
└──────┬──────┘
       │
       ▼
┌─────────────┐
│ pandocr-web │  (已有,改动 < 30 行)
└──────┬──────┘
       │  POST /pipeline
       ▼
┌──────────────────────┐
│  Preprocess Gateway  │  ← 编排中枢,纯逻辑
└──┬──────┬──────┬─────┘
   │      │      │
   ▼      ▼      ▼
┌──────┐┌──────┐┌──────┐
│质量评││矫正  ││分类  │
│估    ││服务  ││服务  │
└──────┘└──────┘└──────┘
   │      │      │
   └──────┴──────┘
          │
          ▼
   (返回 cleaned image + 分类结果 + OCR 路由建议)
          │
          ▼
┌─────────────────────────┐
│  PaddleOCR 推理服务群   │  (已有,不动)
└─────────────────────────┘
```

## 三、服务清单

| 服务 | 路径 | 端口 | 模型 | 状态 |
|---|---|---|---|---|
| **矫正服务** | `preprocess/correction/` | 8084 | `cv_resnet18_card_correction` (ONNX) | 🚧 骨架阶段 |
| **分类服务** | `preprocess/classify/` | 8085 | 待定 (PaddleClas / CLIP) | 📝 计划中 |
| **质量评估** | (规划中) | 8086 | 待定 | 💭 想法 |
| **Gateway** | `preprocess/gateway/` | 8087 | 无 ML,纯编排 | 🚧 骨架阶段 |

## 四、目录结构

```
preprocess/
├── README.md                  ← 你正在看的
├── ARCHITECTURE.md            ← 详细设计
├── correction/                ← 矫正服务
│   ├── app.py                 ← FastAPI 入口
│   ├── inference.py           ← ONNX 推理封装
│   ├── Dockerfile
│   ├── requirements.txt
│   ├── models/                ← 模型权重(.gitignore)
│   └── tests/
├── classify/                  ← 分类服务
│   └── README.md              ← 占位
└── gateway/                   ← 编排网关
    ├── app.py
    ├── config/
    │   └── pipeline.yaml      ← 编排规则(可热改)
    ├── Dockerfile
    └── requirements.txt
```

## 五、核心设计原则

1. **Pandocr-web 最小改动** —— 只改 1 个环境变量 + 30 行,核心业务代码不动
2. **Gateway 纯编排** —— 不带模型,只做路由和组合,故障时自动降级
3. **服务可插拔** —— 任何前置服务挂了,Gateway 跳过该步继续走,标注 `stage_results: {skipped: true}`
4. **规则可配置** —— pipeline.yaml 决定编排顺序,改 YAML 即可调流程,不需要重发版
5. **Prometheus 友好** —— 所有服务暴露 `/metrics`,Gateway 聚合全链路时延

## 六、上游 / 下游契约

### 上游(从 pandocr-web 来)

```http
POST /pipeline
Content-Type: multipart/form-data

file: <image or PDF page>
```

### 下游(到 PaddleOCR 推理)

Gateway 返回的 `processed_file` 直接喂给原 PaddleOCR 接口,无破坏性。

### 接口文档

- Gateway: 参见 `preprocess/gateway/README.md`
- 矫正服务: 参见 `preprocess/correction/README.md`

## 七、Roadmap

- [x] **v0.1** 目录骨架 + 架构文档(本周)
- [ ] **v0.2** 矫正服务 ONNX 推理(4090 验证)
- [ ] **v0.3** Gateway 编排 + pandocr-web 接入
- [ ] **v0.4** 评测集 + 矫正前后对比报告(立标杆用)
- [ ] **v1.0** 分类服务接入(L1 业务分类)
- [ ] **v1.1** 路由规则:分类 → OCR 服务选择
- [ ] **v1.2** Prometheus + Grafana 看板
- [ ] **v2.0** K8s Helm Chart

## 八、相关文档

- [ARCHITECTURE.md](./ARCHITECTURE.md) — 详细设计
- [上游项目报告](../../memory/2026-06-27-paddleocr-report.md) — 项目摸底报告(workspace 内存)

---

_维护者: @flyingface | 最后更新: 2026-06-27_
