import cv2
import numpy as np
import onnxruntime as ort
import sys

class YOLO_ONNX_Detector:
    def __init__(self, onnx_path, classes, use_gpu=True, conf_threshold=0.5, iou_threshold=0.5):
        """
        初始化YOLO ONNX推理器

        :param onnx_path: ONNX模型的路径
        :param classes: 类别名称列表, 例如 ['smoke', 'fire']
        :param use_gpu: 是否优先尝试使用GPU
        :param conf_threshold: 置信度阈值
        :param iou_threshold: NMS的IOU阈值
        """
        self.onnx_path = onnx_path
        self.classes = classes
        self.conf_threshold = conf_threshold
        self.iou_threshold = iou_threshold

        # --- 自动设备选择 (GPU/CPU) ---
        providers = ort.get_available_providers()
        chosen_provider = None

        if use_gpu and 'CUDAExecutionProvider' in providers:
            # 如果用户希望使用GPU且CUDA可用
            chosen_provider = ['CUDAExecutionProvider', 'CPUExecutionProvider']
            print("✅ 检测到CUDA，将优先使用GPU进行推理。")
        else:
            # 否则，使用CPU
            chosen_provider = ['CPUExecutionProvider']
            if use_gpu: # 仅当用户意图使用GPU但不可用时发出警告
                print("⚠️ 警告: 未检测到可用的CUDA设备或ONNX Runtime非GPU版本。将自动切换到CPU进行推理。")
            else:
                print("ℹ️ 已配置为使用CPU进行推理。")
        
        # 加载ONNX模型并创建推理会话
        try:
            self.session = ort.InferenceSession(self.onnx_path, providers=chosen_provider)
            # 确认实际使用的设备
            actual_provider = self.session.get_providers()[0]
            print(f"✅ ONNX Runtime 推理器初始化成功，当前使用设备: {actual_provider}")
        except Exception as e:
            print(f"❌ 错误: ONNX模型加载失败。请检查路径是否正确: {self.onnx_path}")
            print(f"错误详情: {e}")
            sys.exit(1) # 模型加载失败则退出程序

        # 获取模型输入信息
        model_input = self.session.get_inputs()[0]
        self.input_name = model_input.name
        self.input_shape = model_input.shape  # 例如 [1, 3, 640, 640]
        self.input_height = self.input_shape[2]
        self.input_width = self.input_shape[3]

    def _preprocess(self, image):
        """对输入图像进行预处理 (Letterbox)"""
        img_h, img_w, _ = image.shape

        # 计算缩放比例，并保持宽高比
        scale = min(self.input_width / img_w, self.input_height / img_h)
        new_w, new_h = int(img_w * scale), int(img_h * scale)

        # 缩放图像
        resized_img = cv2.resize(image, (new_w, new_h), interpolation=cv2.INTER_LINEAR)

        # 创建一个灰色画布，并将缩放后的图像粘贴到中心
        padded_img = np.full((self.input_height, self.input_width, 3), 114, dtype=np.uint8)
        dw, dh = (self.input_width - new_w) // 2, (self.input_height - new_h) // 2
        padded_img[dh:dh + new_h, dw:dw + new_w, :] = resized_img

        # 转换 BGR -> RGB, HWC -> CHW, 归一化
        img_rgb = padded_img[:, :, ::-1]
        img_transposed = np.transpose(img_rgb, (2, 0, 1))
        img_normalized = img_transposed.astype(np.float32) / 255.0

        # 增加batch维度
        input_tensor = np.expand_dims(img_normalized, axis=0)

        return input_tensor, scale, dw, dh

    def _postprocess(self, output, scale, dw, dh):
        """对模型输出进行后处理"""
        # Ultralytics导出的ONNX输出形状通常是 [1, 6, 8400] -> [batch, 4_bbox+num_classes, num_proposals]
        # 我们需要将其转置为 [1, 8400, 6]
        predictions = np.squeeze(output).T

        # 过滤掉置信度低的检测结果
        # 获取所有框中，每个类别的最高分
        scores = np.max(predictions[:, 4:], axis=1)
        predictions = predictions[scores > self.conf_threshold, :]
        scores = scores[scores > self.conf_threshold]

        if predictions.shape[0] == 0:
            return [], [], []

        # 获取类别ID
        class_ids = np.argmax(predictions[:, 4:], axis=1)

        # 将 (x_center, y_center, w, h) 格式的框转换为 (x1, y1, x2, y2)
        boxes = self._xywh2xyxy(predictions[:, :4])

        # 调整坐标以匹配原始图像尺寸
        boxes -= np.array([dw, dh, dw, dh])
        boxes /= scale

        # 应用非极大值抑制 (NMS)
        indices = cv2.dnn.NMSBoxes(boxes.tolist(), scores.tolist(), self.conf_threshold, self.iou_threshold)

        # 提取最终结果
        final_boxes = boxes[indices]
        final_scores = scores[indices]
        final_class_ids = class_ids[indices]

        return final_boxes, final_scores, final_class_ids

    def _xywh2xyxy(self, xywh):
        """(x_center, y_center, w, h) -> (x1, y1, x2, y2)"""
        xy, wh = xywh[:, 0:2], xywh[:, 2:4]
        xy1 = xy - wh / 2
        xy2 = xy + wh / 2
        return np.concatenate([xy1, xy2], axis=1)

    def draw_detections(self, image, boxes, scores, class_ids):
        """在图像上绘制检测结果"""
        for box, score, class_id in zip(boxes, scores, class_ids):
            x1, y1, x2, y2 = box.astype(int)
            label = f"{self.classes[class_id]}: {score:.2f}"
            
            # fire为红色, smoke为绿色
            color = (0, 0, 255) if self.classes[class_id] == 'fire' else (0, 255, 0)
            cv2.rectangle(image, (x1, y1), (x2, y2), color, 2)
            cv2.putText(image, label, (x1, y1 - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.7, color, 2)
        return image

    def detect(self, image_path):
        """
        执行完整的检测流程
        :param image_path: 输入图像的路径
        :return: 带有检测结果的图像
        """
        original_image = cv2.imread(image_path)
        if original_image is None:
            print(f"❌ 错误: 无法读取图片 {image_path}")
            return None

        # 预处理
        input_tensor, scale, dw, dh = self._preprocess(original_image)

        # 执行推理
        outputs = self.session.run(None, {self.input_name: input_tensor})

        # 后处理
        boxes, scores, class_ids = self._postprocess(outputs[0], scale, dw, dh)

        # 绘制结果
        result_image = self.draw_detections(original_image, boxes, scores, class_ids)

        return result_image

if __name__ == '__main__':
    # --- 配置参数 ---
    ONNX_MODEL_PATH = "smoke_fire_s.onnx"
    IMAGE_PATH = "./test.png"  # <<-- 替换为你的测试图片路径
    CLASSES = ['smoke', 'fire']  # <<-- 你的类别，顺序必须和训练时一致
    OUTPUT_IMAGE_PATH = "result_onnx.jpg"
    USE_GPU = True # <<-- 在此设置是否优先使用GPU

    # --- 执行检测 ---
    print("🚀 开始进行ONNX模型推理...")

    # 1. 检查依赖 (可选，但推荐)
    try:
        import onnxruntime
    except ImportError:
        print("❌ 错误: onnxruntime 未安装。请运行 'pip install onnxruntime-gpu' (推荐) 或 'pip install onnxruntime'。")
        sys.exit(1)

    # 2. 初始化检测器 (内部已包含设备检测和模型加载)
    detector = YOLO_ONNX_Detector(
        onnx_path=ONNX_MODEL_PATH, 
        classes=CLASSES,
        use_gpu=USE_GPU
    )

    # 3. 对单张图片进行检测
    print(f"\n🔍 正在检测图片: {IMAGE_PATH}")
    result_img = detector.detect(image_path=IMAGE_PATH)

    # 4. 保存或显示结果
    if result_img is not None:
        cv2.imwrite(OUTPUT_IMAGE_PATH, result_img)
        print(f"✅ 检测完成! 结果已保存至: {OUTPUT_IMAGE_PATH}")
        # 如果你想直接显示图片，可以取消下面的注释
        # cv2.imshow("ONNX Detection Result", result_img)
        # cv2.waitKey(0)
        # cv2.destroyAllWindows()