# app/service/detection_service.py
import asyncio
import uuid
from datetime import datetime, timedelta
from typing import Dict, List, Any

from fastapi import HTTPException, status

from app.cfg.config import AppSettings
from app.cfg.logging import app_logger
from app.core.model_manager import ModelPool
from app.core.pipeline import VideoStreamPipeline
from app.schema.detection_schema import ActiveStreamInfo, StreamStartRequest


class DetectionService:
    """
    封装核心业务逻辑的服务类 (Hailo版)。
    """

    def __init__(self, settings: AppSettings, model_pool: ModelPool):
        app_logger.info("正在初始化 DetectionService (Hailo版)...")
        self.settings = settings
        self.model_pool = model_pool
        self.active_streams: Dict[str, VideoStreamPipeline] = {}
        self.stream_infos: Dict[str, ActiveStreamInfo] = {}
        self.stream_lock = asyncio.Lock()

    async def start_stream(self, req: StreamStartRequest) -> ActiveStreamInfo:
        """启动一个新的视频流处理任务。"""
        stream_id = str(uuid.uuid4())
        lifetime = req.lifetime_minutes if req.lifetime_minutes is not None else self.settings.app.stream_default_lifetime_minutes

        async with self.stream_lock:
            frame_queue = asyncio.Queue(maxsize=self.settings.app.stream_max_queue_size)

            # 注意：pipeline.start() 是一个阻塞方法，它会等待流水线结束或失败
            # 因此，我们需要在一个独立的asyncio任务中运行它
            pipeline = VideoStreamPipeline(
                settings=self.settings,
                stream_id=stream_id,
                video_source=req.source,
                output_queue=frame_queue,
                model_pool=self.model_pool
            )
            # 在后台任务中运行 pipeline.start()
            asyncio.create_task(asyncio.to_thread(pipeline.start))

            # 修改点：等待流水线中的所有线程真正启动
            # 给予一个合理的超时时间，例如 5 秒
            try:
                await asyncio.to_thread(pipeline.threads_started_event.wait, timeout=5.0)
            except TimeoutError:
                app_logger.error(f"【流水线 {stream_id}】启动超时，线程未在预期时间内启动。")
                raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "服务正忙或无法启动处理线程，请稍后再试。")


            # 修正点：检查线程列表是否为空，以及是否有任何一个线程在运行
            # 这里的检查现在应该在 threads_started_event.wait 成功后执行
            if not pipeline.threads or not any(t.is_alive() for t in pipeline.threads):
                raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "服务正忙或无法启动处理线程，请稍后再试。")

            self.active_streams[stream_id] = pipeline
            started_at = datetime.now()
            expires_at = None if lifetime == -1 else started_at + timedelta(minutes=lifetime)
            stream_info = ActiveStreamInfo(stream_id=stream_id, source=req.source, started_at=started_at,
                                           expires_at=expires_at, lifetime_minutes=lifetime)
            self.stream_infos[stream_id] = stream_info

            app_logger.info(f"🚀 视频流处理线程组已启动: ID={stream_id}, 源={req.source}")
            return stream_info

    async def stop_stream(self, stream_id: str) -> bool:
        """停止一个指定的视频流。"""
        async with self.stream_lock:
            pipeline = self.active_streams.pop(stream_id, None)
            _ = self.stream_infos.pop(stream_id, None)
            if not pipeline:
                app_logger.warning(f"尝试停止一个不存在或已被停止的流: {stream_id}")
                return False

        # 在独立的线程中执行阻塞的stop方法，避免阻塞FastAPI的事件循环
        await asyncio.to_thread(pipeline.stop)
        app_logger.info(f"✅ 视频流流水线已请求停止: ID={stream_id}")
        return True

    async def get_stream_feed(self, stream_id: str):
        """从指定流水线的输出队列获取帧。"""
        async with self.stream_lock:
            pipeline = self.active_streams.get(stream_id)

        if not pipeline:
            app_logger.warning(f"客户端尝试连接一个不存在或已停止的流: {stream_id}")
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Stream not found or already stopped.")

        frame_queue = pipeline.output_queue
        try:
            while True:
                # 修正点：检查是否所有后台线程都已停止
                # 额外的检查：如果 stop_event 被设置了，也应该停止推送
                if pipeline.stop_event.is_set() or (not pipeline.threads or (not any(t.is_alive() for t in pipeline.threads) and frame_queue.empty())):
                    app_logger.info(f"检测到流 {stream_id} 的所有后台线程已停止，正常关闭推送。")
                    break


                try:
                    frame_bytes = await asyncio.wait_for(frame_queue.get(), timeout=1.0)
                    if frame_bytes is None:
                        continue
                    yield (b'--frame\r\n'
                           b'Content-Type: image/jpeg\r\n\r\n' + frame_bytes + b'\r\n')
                    frame_queue.task_done()
                except asyncio.TimeoutError:
                    continue

        except asyncio.CancelledError:
            app_logger.info(f"客户端从流 {stream_id} 断开连接。")
            await self.stop_stream(stream_id)
            raise

    async def get_all_active_streams_info(self) -> List[ActiveStreamInfo]:
        """获取所有当前活动流的信息列表。"""
        async with self.stream_lock:
            # 清理已经意外死掉的流
            dead_stream_ids = [sid for sid, p in self.active_streams.items() if
                               not p.threads or not any(t.is_alive() for t in p.threads)]
            for sid in dead_stream_ids:
                self.active_streams.pop(sid, None)
                self.stream_infos.pop(sid, None)
                app_logger.warning(f"检测并清理了一个意外终止的流: {sid}")

            return list(self.stream_infos.values())

    async def cleanup_expired_streams(self):
        """[后台任务] - 定期检查并清理所有已过期的视频流。"""
        while True:
            await asyncio.sleep(self.settings.app.stream_cleanup_interval_seconds)
            now = datetime.now()
            streams_to_check = list(self.stream_infos.items())
            expired_stream_ids = [sid for sid, info in streams_to_check if info.expires_at and now >= info.expires_at]

            if expired_stream_ids:
                app_logger.info(f"🗑️ 发现 {len(expired_stream_ids)} 个过期视频流，正在清理: {expired_stream_ids}")
                cleanup_tasks = [self.stop_stream(stream_id) for stream_id in expired_stream_ids]
                await asyncio.gather(*cleanup_tasks)

    async def stop_all_streams(self):
        """在应用关闭时，停止所有活动的视频流。"""
        app_logger.info("应用准备关闭，正在停止所有活动的视频流...")
        async with self.stream_lock:
            all_stream_ids = list(self.active_streams.keys())
        if all_stream_ids:
            stop_tasks = [self.stop_stream(stream_id) for stream_id in all_stream_ids]
            await asyncio.gather(*stop_tasks)
            app_logger.info(f"✅ 所有 {len(all_stream_ids)} 个活动流已清理完毕。")