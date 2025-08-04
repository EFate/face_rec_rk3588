# app/router/detection_router.py
from fastapi import APIRouter, Depends, Request, HTTPException, status
from fastapi.responses import StreamingResponse

from app.schema.detection_schema import (
    ApiResponse, StreamDetail, GetAllStreamsResponseData,
    StreamStartRequest, StopStreamResponseData, HealthCheckResponseData
)
from app.service.detection_service import DetectionService

router = APIRouter()


def get_detection_service(request: Request) -> DetectionService:
    """
    依赖注入函数 (Dependency Injection)。
    FastAPI 会在处理请求时调用这个函数，从应用状态 `request.app.state` 中获取
    DetectionService 的单例实例，并将其作为参数传递给路径操作函数。
    这确保了所有请求都共享同一个服务实例，从而共享状态（如活动流列表）。
    """
    return request.app.state.detection_service


@router.get(
    "/health",
    response_model=ApiResponse[HealthCheckResponseData],
    summary="健康检查",
    description="检查服务是否正常运行。可用于负载均衡器或服务监控（如Kubernetes的liveness probe）。",
    tags=["系统状态"]
)
async def health_check():
    """返回服务当前状态，表明服务已启动并可接受请求。"""
    return ApiResponse(data=HealthCheckResponseData())


@router.post(
    "/streams/start",
    response_model=ApiResponse[StreamDetail],
    summary="启动一个视频流检测任务",
    description="提供一个视频源（摄像头ID、视频文件路径或URL），启动一个新的后台检测任务。",
    status_code=status.HTTP_201_CREATED,  # 使用 201 表示资源已成功创建
    tags=["视频流管理"]
)
async def start_stream(
        request: Request,
        start_request: StreamStartRequest,
        service: DetectionService = Depends(get_detection_service)
):
    """处理启动流的请求，返回新创建流的详细信息，包括用于播放的URL。"""
    stream_info = await service.start_stream(start_request)

    # 使用 request.url_for 动态生成可访问的视频流 URL。
    # 这种方法比硬编码URL（如 f"/api/detection/streams/feed/{stream_info.stream_id}"）更健壮，
    # 因为它会自动处理应用的根路径(root_path)等前缀，在反向代理后也能正常工作。
    feed_url = request.url_for('get_stream_feed', stream_id=stream_info.stream_id)
    response_data = StreamDetail(**stream_info.model_dump(), feed_url=str(feed_url))

    # 关键点：区分 HTTP 状态码和业务状态码。
    # HTTP 状态码（201 CREATED）由装饰器 `status_code` 参数决定，表示请求在传输层成功。
    # `ApiResponse` 中的 `code=0` 是我们自定义的业务层状态码，表示业务逻辑执行成功。
    return ApiResponse(data=response_data, msg="视频流已成功启动")


@router.get(
    "/streams/feed/{stream_id}",
    summary="获取指定ID的视频流数据",
    description="通过此端点获取实时处理后的视频流，格式为 multipart/x-mixed-replace。",
    tags=["视频流管理"],
    name="get_stream_feed",  # 为此路由命名，是 `url_for` 能够找到它的关键
    responses={
        200: {"content": {"multipart/x-mixed-replace; boundary=frame": {}}, "description": "成功返回视频流。"},
        404: {"description": "指定的 stream_id 未找到或已停止。"}
    }
)
async def get_stream_feed(
        stream_id: str,
        service: DetectionService = Depends(get_detection_service)
):
    """返回一个流式响应，将后台处理的帧实时推送给客户端。"""
    return StreamingResponse(
        service.get_stream_feed(stream_id),  # `get_stream_feed` 是一个异步生成器
        media_type="multipart/x-mixed-replace; boundary=frame"
    )


@router.post(
    "/streams/stop/{stream_id}",
    response_model=ApiResponse[StopStreamResponseData],
    summary="停止一个指定的视频流",
    description="根据 stream_id 停止对应的后台检测任务，并释放相关资源。",
    tags=["视频流管理"]
)
async def stop_stream(
        stream_id: str,
        service: DetectionService = Depends(get_detection_service)
):
    """处理停止流的请求。"""
    success = await service.stop_stream(stream_id)
    if not success:
        # 如果 service 层返回 False，说明流不存在，抛出 404 异常。
        # 这个异常会被 main.py 中定义的全局异常处理器捕获，并返回标准格式的JSON错误响应。
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"ID为 '{stream_id}' 的视频流未找到。")

    return ApiResponse(data=StopStreamResponseData(stream_id=stream_id))


@router.get(
    "/streams",
    response_model=ApiResponse[GetAllStreamsResponseData],
    summary="获取所有活动的视频流列表",
    description="返回一个列表，包含所有当前正在运行的视频流的详细信息。",
    tags=["视频流管理"]
)
async def get_all_streams(
        request: Request,
        service: DetectionService = Depends(get_detection_service)
):
    """获取所有活动流的信息，并为每个流动态生成其播放 URL。"""
    active_streams_info = await service.get_all_active_streams_info()
    streams_with_details = [
        StreamDetail(
            **info.model_dump(),
            feed_url=str(request.url_for('get_stream_feed', stream_id=info.stream_id))
        )
        for info in active_streams_info
    ]
    response_data = GetAllStreamsResponseData(
        active_streams_count=len(streams_with_details),
        streams=streams_with_details
    )
    return ApiResponse(data=response_data)