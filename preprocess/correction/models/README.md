# 模型权重 (Models)

> ⚠️ **不要把模型权重提交到 git!**

模型文件应放在本目录,但通过 `.gitignore` 排除。
本目录下的 `.gitkeep` 仅占位,保证目录结构。

## 加载方式

- **开发**:手动放到这里,代码直接读 `./models/xxx.onnx`
- **Docker**:volume 挂载,例如 `-v ./models:/models`
- **K8s**:用 PVC 或 InitContainer 下载

## 矫正服务需要的文件

```
models/
├── cv_resnet18_card_correction.onnx        # 模型权重
└── cv_resnet18_card_correction.meta         # 元信息(JSON)
```

> 模型获取方式:从上游仓库 / 内部模型仓库 / 飞书云盘。
> **不要写死 URL 在代码里,放环境变量**。

## 未来扩展

```
models/
├── correction/                              # 矫正模型
├── classify/                                # 分类模型
└── quality/                                 # 质量评估模型(可选)
```
