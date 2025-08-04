# app/core/processing.py
from typing import List
import cv2
import numpy as np



def draw_detections(
        image: np.ndarray,
        detections: List[dict],
        class_names: List[str]  # 确保 class_names 的顺序与模型训练时一致
):
    """
    在图像上绘制 degirum 模型返回的检测结果。

    Args:
        image (np.ndarray): 原始的OpenCV图像。
        detections (List[dict]): a `model.predict()` call.
                                  每个字典包含 'bbox', 'score', 'label'。
        class_names (List[str]): 模型支持的类别名称列表。
    """
    # 定义颜色映射，可以根据需要扩展
    colors = {"smoke": (160, 32, 240), "fire": (0, 0, 255)}

    for det in detections:
        # 从结果字典中提取信息
        box = det.get('bbox')
        score = det.get('score', 0.0)
        label = det.get('label', '')

        if not box:
            continue

        x1, y1, x2, y2 = map(int, box)

        # 获取颜色和显示的标签文本
        color = colors.get(label, (0, 255, 0))  # 如果有未知类别，默认为绿色
        display_text = f"{label}: {score:.2f}"

        # 绘制矩形框和标签
        cv2.rectangle(image, (x1, y1), (x2, y2), color, 2)
        cv2.putText(image, display_text, (x1, y1 - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.7, color, 2)

    return image