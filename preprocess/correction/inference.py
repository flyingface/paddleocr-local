"""矫正服务 - ONNX 推理封装

职责: 加载 cv_resnet18_card_correction 模型,对输入图像做几何矫正。
输入: BGR uint8 图像 (numpy array)
输出: 矫正后的 BGR uint8 图像,4 个角点 (x1,y1,x2,y2,x3,y3,x4,y4),置信度
"""
import os
import logging
from pathlib import Path
from typing import Tuple, Optional

import cv2
import numpy as np
import onnxruntime as ort

logger = logging.getLogger("preprocess.correction")


class CorrectionEngine:
    """ONNX 推理引擎单例

    设计:
    - 启动时加载一次模型,常驻显存
    - 推理时只做前向 + 后处理
    - 不做业务逻辑(那是 FastAPI 层的事)
    """

    # 模型输入尺寸 (cv_resnet18_card_correction 默认)
    INPUT_SIZE = (224, 224)
    # 输入标准化参数 (ImageNet 标准,大多数 resnet 都用这个)
    MEAN = np.array([0.485, 0.456, 0.406], dtype=np.float32)
    STD = np.array([0.229, 0.224, 0.225], dtype=np.float32)

    def __init__(
        self,
        model_path: str = os.getenv("CORRECTION_MODEL_PATH", "/models/cv_resnet18_card_correction.onnx"),
        providers: Optional[list] = None,
    ):
        self.model_path = Path(model_path)
        if not self.model_path.exists():
            raise FileNotFoundError(
                f"模型文件不存在: {self.model_path}\n"
                f"请把 ONNX 模型放到该路径,或通过 CORRECTION_MODEL_PATH 环境变量指定。"
            )

        # 优先级: CUDA > CPU
        if providers is None:
            available = ort.get_available_providers()
            if "CUDAExecutionProvider" in available:
                providers = [
                    ("CUDAExecutionProvider", {"device_id": 0}),
                    "CPUExecutionProvider",
                ]
            else:
                providers = ["CPUExecutionProvider"]
                logger.warning("CUDA 不可用,回退到 CPU 推理 (延迟会显著增加)")

        logger.info("加载矫正模型: %s", self.model_path)
        logger.info("推理后端: %s", providers)

        self.session = ort.InferenceSession(
            str(self.model_path),
            providers=providers,
        )

        # 读输入输出信息
        self.input_name = self.session.get_inputs()[0].name
        self.input_shape = self.session.get_inputs()[0].shape
        self.output_names = [o.name for o in self.session.get_outputs()]
        logger.info("模型输入: %s %s", self.input_name, self.input_shape)
        logger.info("模型输出: %s", self.output_names)

    def _preprocess(self, image: np.ndarray) -> np.ndarray:
        """预处理: BGR -> RGB -> resize -> normalize -> NCHW

        Args:
            image: HWC BGR uint8

        Returns:
            NCHW float32,已标准化
        """
        # BGR -> RGB
        img = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
        # resize
        img = cv2.resize(img, self.INPUT_SIZE, interpolation=cv2.INTER_LINEAR)
        # uint8 -> float32, 归一化到 [0,1]
        img = img.astype(np.float32) / 255.0
        # 标准化
        img = (img - self.MEAN) / self.STD
        # HWC -> NCHW
        img = np.transpose(img, (2, 0, 1))
        img = np.expand_dims(img, axis=0)
        return img

    def _postprocess(
        self, output: np.ndarray, orig_shape: Tuple[int, int]
    ) -> Tuple[np.ndarray, float]:
        """后处理: 模型输出 -> 4 个角点 + 置信度

        模型输出格式(常见): [batch, 8]  4 个点 (x,y) 归一化到 [0,1]
        或: [batch, 9] 前 8 是点,最后是置信度
        """
        flat = output.flatten()

        if len(flat) >= 9:
            points_norm = flat[:8]
            confidence = float(flat[8])
        else:
            points_norm = flat[:8]
            confidence = 1.0  # 模型没输出置信度,默认 1.0

        h, w = orig_shape
        points = []
        for i in range(4):
            x = float(points_norm[2 * i] * w)
            y = float(points_norm[2 * i + 1] * h)
            points.append([x, y])

        return np.array(points, dtype=np.float32), confidence

    @staticmethod
    def _order_points(pts: np.ndarray) -> np.ndarray:
        """将 4 个角点排序为: 左上、右上、右下、左下

        这是透视变换的标准做法,确保变换后图像方向正确。
        """
        rect = np.zeros((4, 2), dtype=np.float32)
        s = pts.sum(axis=1)
        rect[0] = pts[np.argmin(s)]      # 左上: x+y 最小
        rect[2] = pts[np.argmax(s)]      # 右下: x+y 最大
        diff = np.diff(pts, axis=1)
        rect[1] = pts[np.argmin(diff)]   # 右上: y-x 最小
        rect[3] = pts[np.argmax(diff)]   # 左下: y-x 最大
        return rect

    def correct(self, image: np.ndarray) -> dict:
        """对单张图像做矫正

        Args:
            image: BGR uint8 (H, W, C)

        Returns:
            {
                "corrected_image": BGR uint8,
                "corner_points": [[x1,y1], [x2,y2], [x3,y3], [x4,y4]],
                "confidence": float,
                "applied": bool  # 置信度太低时不矫正,返回原图
            }
        """
        if image is None or image.size == 0:
            raise ValueError("输入图像为空")

        orig_h, orig_w = image.shape[:2]

        # 推理
        input_tensor = self._preprocess(image)
        outputs = self.session.run(self.output_names, {self.input_name: input_tensor})
        raw_output = outputs[0]

        # 后处理
        points, confidence = self._postprocess(raw_output, (orig_h, orig_w))

        # 置信度太低 → 不矫正
        CONFIDENCE_THRESHOLD = float(os.getenv("CORRECTION_CONFIDENCE_THRESHOLD", "0.5"))
        if confidence < CONFIDENCE_THRESHOLD:
            logger.info("置信度 %.3f < %.3f,跳过矫正", confidence, CONFIDENCE_THRESHOLD)
            return {
                "corrected_image": image,
                "corner_points": points.tolist(),
                "confidence": confidence,
                "applied": False,
            }

        # 排序角点 + 透视变换
        rect = self._order_points(points)
        (tl, tr, br, bl) = rect

        # 计算矫正后图像的宽高
        width_a = np.linalg.norm(br - bl)
        width_b = np.linalg.norm(tr - tl)
        max_w = int(max(width_a, width_b))

        height_a = np.linalg.norm(tr - br)
        height_b = np.linalg.norm(tl - bl)
        max_h = int(max(height_a, height_b))

        # 构造目标坐标
        dst = np.array(
            [[0, 0], [max_w - 1, 0], [max_w - 1, max_h - 1], [0, max_h - 1]],
            dtype=np.float32,
        )

        # 透视变换
        M = cv2.getPerspectiveTransform(rect, dst)
        warped = cv2.warpPerspective(image, M, (max_w, max_h))

        return {
            "corrected_image": warped,
            "corner_points": rect.tolist(),
            "confidence": confidence,
            "applied": True,
        }
