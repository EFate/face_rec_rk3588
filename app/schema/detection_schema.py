# app/schema/detection_schema.py
from pydantic import BaseModel, Field
from typing import List, Optional, TypeVar, Generic
from datetime import datetime

# --- 通用 API 响应模型 ---
# 使用 Python 的泛型 (Generic) 和类型变量 (TypeVar)，我们可以创建一个
# 可以包裹任何类型数据的标准响应模型
T = TypeVar("T")

class ApiResponse(BaseModel, Generic[T]):
    """
    标准化的API响应体结构。
    所有API端点都应返回此结构，以便前端或客户端能够统一处理。
    """
    code: int = Field(0, description="响应状态码，0表示成功，其它非零值表示特定的业务失败")
    msg: str = Field("Success", description="响应消息，提供操作结果的文本描述")
    data: Optional[T] = Field(None, description="实际的响应数据。其具体结构由泛型 T 决定。")

# --- 健康检查响应模型 ---
class HealthCheckResponseData(BaseModel):
    """健康检查端点 `/health` 的响应数据模型。"""
    status: str = Field("ok", description="服务状态，'ok' 表示正常")
    message: str = Field("烟火检测服务正常运行。", description="服务状态的详细信息")

# --- 视频流管理 Schema ---
class StreamStartRequest(BaseModel):
    """启动视频流的请求体 `/streams/start` (POST)。"""
    source: str = Field(
        ...,
        description="视频源。可以是本地摄像头ID(如 '0')，或视频文件的本地/网络路径(URL)",
        example="0"
    )
    lifetime_minutes: Optional[int] = Field(
        None,
        description="视频流生命周期（分钟）。-1表示永久，不填(null)则使用配置文件中的默认值。",
        example=10
    )

class ActiveStreamInfo(BaseModel):
    """描述一个活动视频流的内部基础信息，不直接暴露给用户。"""
    stream_id: str = Field(..., description="由系统生成的流的唯一ID (UUID)")
    source: str = Field(..., description="该流使用的原始视频源")
    started_at: datetime = Field(..., description="流的启动时间 (UTC时间)")
    expires_at: Optional[datetime] = Field(None, description="流的计划过期时间 (UTC时间)，None表示永不过期")
    lifetime_minutes: int = Field(..., description="配置的生命周期（分钟），-1表示永久")

class StreamDetail(ActiveStreamInfo):
    """
    返回给客户端的、包含完整可访问信息的流详情。
    继承自 `ActiveStreamInfo` 并增加了 `feed_url`。
    """
    feed_url: str = Field(..., description="用于在浏览器或播放器中查看该视频流的完整URL")

class StopStreamResponseData(BaseModel):
    """停止视频流操作 `/streams/stop/{stream_id}` (POST) 的响应数据。"""
    stream_id: str = Field(..., description="被成功停止的流的ID")
    message: str = Field("Stream stopped successfully.", description="操作结果信息", readOnly=True)

class GetAllStreamsResponseData(BaseModel):
    """获取所有活动视频流列表 `/streams` (GET) 的响应数据。"""
    active_streams_count: int = Field(..., description="当前活动的视频流总数")
    streams: List[StreamDetail] = Field([], description="所有活动视频流的详细信息列表")