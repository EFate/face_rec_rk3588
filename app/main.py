# app/main.py
import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request, status
from fastapi.exceptions import HTTPException
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware

from app.cfg.config import get_app_settings
from app.cfg.logging import app_logger, setup_logging
# 核心修改：导入 ModelPool
from app.core.model_manager import ModelPool
from app.router.detection_router import router as detection_router
from app.router.device_router import router as device_router
from app.schema.detection_schema import ApiResponse
from app.service.detection_service import DetectionService


settings = get_app_settings()
setup_logging(settings)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    应用生命周期管理器 (Hailo版)。
    """
    # --- 启动任务 ---
    app_logger.info("🚀 应用启动中 (Hailo版)...")

    # 1. 初始化 DeGirum 模型池。这是一个耗时的I/O和硬件交互任务。
    model_pool = ModelPool(
        settings=settings,
        pool_size=settings.app.max_concurrent_tasks
    )
    app.state.model_pool = model_pool

    # 2. 初始化核心服务，并注入模型池
    detection_service = DetectionService(settings=settings, model_pool=model_pool)
    app.state.detection_service = detection_service
    app_logger.info("✅ 检测服务 (DetectionService) 初始化完成。")

    # 3. 创建并启动后台清理任务
    cleanup_task = asyncio.create_task(detection_service.cleanup_expired_streams())
    app.state.cleanup_task = cleanup_task
    app_logger.info("✅ 已启动过期视频流的周期性清理任务。")

    app_logger.info("🎉 应用启动成功，准备接收请求！")

    yield

    # --- 关闭任务 ---
    app_logger.info("👋 应用关闭中...")

    # 1. 优雅地取消后台清理任务
    if hasattr(app.state, 'cleanup_task'):
        cleanup_task = app.state.cleanup_task
        if cleanup_task and not cleanup_task.done():
            cleanup_task.cancel()
            try:
                await cleanup_task
            except asyncio.CancelledError:
                app_logger.info("✅ 视频流清理任务已成功取消。")

    # 2. 停止所有正在运行的视频流
    if hasattr(app.state, 'detection_service'):
        await app.state.detection_service.stop_all_streams()

    # 3. 释放模型池资源，并强制清理后台进程
    if hasattr(app.state, 'model_pool'):
        app.state.model_pool.dispose()


    app_logger.info("✅ 所有关闭任务已完成。应用已安全退出。")


def create_app() -> FastAPI:
    """创建并配置 FastAPI 应用实例的工厂函数。"""
    app = FastAPI(
        lifespan=lifespan,
        title=settings.app.title,
        description=settings.app.description,
        version=settings.app.version,
        debug=settings.app.debug,
        docs_url=None,
        redoc_url=None,
    )

    # --- 全局异常处理器 (保持不变) ---
    @app.exception_handler(HTTPException)
    async def http_exception_handler(request: Request, exc: HTTPException):
        return JSONResponse(
            status_code=exc.status_code,
            content=ApiResponse(code=exc.status_code, msg=exc.detail).model_dump()
        )

    @app.exception_handler(Exception)
    async def generic_exception_handler(request: Request, exc: Exception):
        app_logger.exception(f"在处理请求 {request.url} 时发生未处理的异常: {exc}")
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content=ApiResponse(code=500, msg="服务器内部错误，请联系管理员。").model_dump()
        )

    # --- 挂载路由和静态文件 (保持不变) ---
    app.include_router(detection_router, prefix="/api/detection", tags=["烟火检测服务"])
    app.include_router(device_router, prefix="/api/device", tags=["Hailo设备"])
    STATIC_FILES_DIR = Path(__file__).parent / "static"
    if STATIC_FILES_DIR.is_dir():
        app.mount("/static", StaticFiles(directory=STATIC_FILES_DIR), name="static")

    # --- 自定义文档路由 (保持不变) ---
    @app.get("/docs", include_in_schema=False)
    async def custom_swagger_ui_html():
        return get_swagger_ui_html(
            openapi_url=app.openapi_url,
            title=app.title + " - API 文档",
            swagger_js_url="/static/swagger-ui/swagger-ui-bundle.js",
            swagger_css_url="/static/swagger-ui/swagger-ui.css",
        )

    @app.get("/", tags=["System"], include_in_schema=False)
    async def read_root():
        return {"message": f"欢迎使用 {settings.app.title}!", "docs_url": "/docs"}

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    return app


app = create_app()