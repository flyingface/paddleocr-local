# 矫正服务 (Correction Service)

> 用 `cv_resnet18_card_correction` 对输入图像做**几何矫正** —— 把歪斜的卡证 / 拍照件拉成正矩形。

## 状态

🚧 **骨架阶段** — 目录、文档、Dockerfile 已就位,代码待补。

## 接口

```http
POST /correct
Content-Type: multipart/form-data

file: <image>
```

返回:

```json
{
  "corrected_image_b64": "...",
  "applied": true,
  "confidence": 0.96,
  "corner_points": [[12, 34], [500, 28], [512, 380], [8, 392]],
  "latency_ms": 47
}
```

## 依赖

- ONNX Runtime GPU
- OpenCV
- Pillow
- 模型权重(放 `models/`,`.gitignore` 已配)

## 本地开发

```bash
# 1. 放模型到 models/ 目录
ls models/
#  cv_resnet18_card_correction.onnx
#  cv_resnet18_card_correction.meta

# 2. 启动
docker build -t paddleocr-preprocess-correction .
docker run --gpus all -p 8084:8080 \
  -v $(pwd)/models:/models \
  paddleocr-preprocess-correction

# 3. 测试
curl -X POST -F "file=@test.jpg" http://localhost:8084/correct
```

## 待办

- [ ] 实现 `app.py` FastAPI 入口
- [ ] 实现 `inference.py` ONNX 推理封装
- [ ] 编写 `tests/test_api.py`
- [ ] 在 `docker-compose.yml` 中注册服务
