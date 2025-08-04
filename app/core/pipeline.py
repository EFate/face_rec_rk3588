# app/core/pipeline.py
import asyncio
import threading
import time
import cv2
import queue
from typing import List

from app.cfg.config import AppSettings
from app.cfg.logging import app_logger
from app.core.model_manager import ModelPool
from app.core.processing import draw_detections


class VideoStreamPipeline:
    """
    封装一个视频流的完整处理流水线。
    采用【参考人脸识别】的四阶段串行处理模式：
    T1: Reader -> T2: Preprocessor -> T3: Inference -> T4: Postprocessor
    """

    def __init__(self, settings: AppSettings, stream_id: str, video_source: str,
                 output_queue: asyncio.Queue, model_pool: ModelPool):
        self.settings = settings
        self.hailo_settings = settings.hailo
        self.stream_id = stream_id
        self.video_source = video_source
        self.output_queue = output_queue  # Web端消费的最终队列
        self.model_pool = model_pool

        # 流水线持有的模型实例
        self.model = None

        # 线程管理
        self.stop_event = threading.Event()
        self.threads: List[threading.Thread] = []
        # 新增：用于指示所有线程是否已成功启动的事件
        self.threads_started_event = threading.Event()

        # 连接各个处理阶段的中间队列
        self.preprocess_queue = queue.Queue(maxsize=30)
        self.inference_queue = queue.Queue(maxsize=30)
        self.postprocess_queue = queue.Queue(maxsize=30)

        self.cap = None  # 视频捕获对象

    def start(self):
        """启动流水线，包括获取模型、打开视频源和启动所有工作线程。"""
        app_logger.info(f"【流水线 {self.stream_id}】正在启动，并尝试获取模型...")
        try:
            # 1. 从模型池中获取一个模型实例供整个流水线使用
            self.model = self.model_pool.acquire(timeout=5.0)
            if self.model is None:
                app_logger.error(f"❌【流水线 {self.stream_id}】启动失败：无法从模型池中获取可用模型。")
                return

            app_logger.info(f"【流水线 {self.stream_id}】成功获取模型，准备打开视频源...")

            # 2. 打开视频源
            source_for_cv = int(self.video_source) if self.video_source.isdigit() else self.video_source
            self.cap = cv2.VideoCapture(source_for_cv)
            if not self.cap.isOpened():
                raise RuntimeError(f"无法打开视频源: {self.video_source}")

            # 3. 启动所有四个线程
            self._start_threads()
            app_logger.info(f"【流水线 {self.stream_id}】所有工作线程已启动。")
            # 标记线程已启动
            self.threads_started_event.set()


            # 4. 主线程监控工作线程的存活状态
            while not self.stop_event.is_set():
                if not all(t.is_alive() for t in self.threads):
                    app_logger.error(f"❌【流水线 {self.stream_id}】检测到有工作线程意外终止。")
                    break
                time.sleep(1)

        except Exception as e:
            app_logger.error(f"❌【流水线 {self.stream_id}】启动或运行时失败: {e}", exc_info=True)
        finally:
            # 确保无论启动成功与否，最终都会调用stop来清理资源
            self.stop()

    def stop(self):
        """有序地停止所有线程并释放所有资源。"""
        if self.stop_event.is_set():
            return
        app_logger.warning(f"【流水线 {self.stream_id}】正在停止...")
        self.stop_event.set()
        # 清除线程已启动事件
        self.threads_started_event.clear()


        # 等待所有线程结束
        for t in self.threads:
            if t.is_alive():
                t.join(timeout=2.0)

        # 释放视频捕捉对象
        if self.cap and self.cap.isOpened():
            self.cap.release()
            app_logger.info(f"【流水线 {self.stream_id}】视频捕捉已释放。")

        # 清空所有中间队列
        for q in [self.preprocess_queue, self.inference_queue, self.postprocess_queue]:
            while not q.empty():
                try:
                    q.get_nowait()
                except queue.Empty:
                    break

        # 归还模型到池中
        if self.model:
            self.model_pool.release(self.model)
            self.model = None
            app_logger.info(f"【流水线 {self.stream_id}】已将模型归还到池中。")

        app_logger.info(f"✅【流水线 {self.stream_id}】所有资源已清理。")

    def _start_threads(self):
        """创建并启动流水线的四个核心线程。"""
        thread_targets = {
            "Reader": self._reader_thread,
            "Preprocessor": self._preprocessor_thread,
            "Inference": self._inference_thread,
            "Postprocessor": self._postprocessor_thread
        }
        for name, target in thread_targets.items():
            thread = threading.Thread(target=target, name=f"{self.stream_id}-{name}", daemon=True)
            self.threads.append(thread)
            thread.start()

    def _reader_thread(self):
        """T1: 从视频源读取帧，放入预处理队列。"""
        app_logger.info(f"【T1:读帧 {self.stream_id}】启动。")
        while not self.stop_event.is_set():
            if not (hasattr(self, 'cap') and self.cap.isOpened()):
                app_logger.warning(f"【T1:读帧 {self.stream_id}】视频源已关闭或不可用。")
                break

            ret, frame = self.cap.read()
            if not ret:
                app_logger.info(f"【T1:读帧 {self.stream_id}】视频源结束。")
                break

            # 保证队列中始终为最新的帧
            if self.preprocess_queue.full():
                try:
                    # 队列已满，丢弃最旧的一帧（队首）
                    self.preprocess_queue.get_nowait()
                except queue.Empty:
                    # 在极罕见的竞争条件下，队列可能在检查后变空，此时忽略即可
                    pass

            # 将最新的帧放入队列
            try:
                self.preprocess_queue.put_nowait(frame)
                time.sleep(0.01)
            except queue.Full:
                # 在极罕见的竞争条件下，队列可能再次被填满，此时放弃本次放入
                pass

        self.preprocess_queue.put(None)  # 发送结束信号
        app_logger.info(f"【T1:读帧 {self.stream_id}】已停止。")

    def _preprocessor_thread(self):
        """T2: 从预处理队列获取帧，传递给推理队列。"""
        app_logger.info(f"【T2:预处理 {self.stream_id}】启动。")
        while not self.stop_event.is_set():
            try:
                frame = self.preprocess_queue.get(timeout=1)
                if frame is None:
                    self.inference_queue.put(None)  # 传递结束信号
                    break

                # 对于烟火检测，Hailo模型直接处理原始帧，故此阶段为直接传递
                self.inference_queue.put(frame)
            except queue.Empty:
                continue
        app_logger.info(f"【T2:预处理 {self.stream_id}】已停止。")

    def _inference_thread(self):
        """T3: 从推理队列获取帧，执行模型推理。"""
        app_logger.info(f"【T3:推理 {self.stream_id}】启动。")
        while not self.stop_event.is_set():
            try:
                frame = self.inference_queue.get(timeout=1)
                if frame is None:
                    self.postprocess_queue.put(None)  # 传递结束信号
                    break

                # 执行推理
                detection_result = self.model.predict(frame)

                # 将原始帧和推理结果一起传递给后处理线程
                self.postprocess_queue.put((frame, detection_result.results))
            except queue.Empty:
                continue
            except Exception as e:
                app_logger.error(f"【T3:推理 {self.stream_id}】发生错误: {e}")

        app_logger.info(f"【T3:推理 {self.stream_id}】已停止。")

    def _postprocessor_thread(self):
        """T4: 获取推理结果，绘制并编码，放入最终输出队列。"""
        app_logger.info(f"【T4:后处理 {self.stream_id}】启动。")
        while not self.stop_event.is_set():
            try:
                data = self.postprocess_queue.get(timeout=1)
                if data is None:
                    break

                original_frame, detections = data

                # 在帧上绘制检测结果
                result_frame = draw_detections(
                    original_frame,
                    detections,
                    self.hailo_settings.class_names
                )

                # 编码为JPEG并放入Web端输出队列
                (flag, encodedImage) = cv2.imencode(".jpg", result_frame)
                if flag:
                    try:
                        self.output_queue.put_nowait(encodedImage.tobytes())
                    except asyncio.QueueFull:
                        pass  # 如果Web端消费慢，则丢弃帧
            except queue.Empty:
                continue
            except Exception as e:
                app_logger.error(f"【T4:后处理 {self.stream_id}】发生错误: {e}")

        try:
            self.output_queue.put_nowait(None)  # 发送最终的结束信号
        except asyncio.QueueFull:
            pass
        app_logger.info(f"【T4:后处理 {self.stream_id}】已停止。")