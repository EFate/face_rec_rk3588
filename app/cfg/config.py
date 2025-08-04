# app/cfg/config.py
import os
import yaml
from pathlib import Path
from typing import Any, List, Optional
from functools import lru_cache
from pydantic import BaseModel, Field, BeforeValidator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from typing_extensions import Annotated


# --- 路径定义 ---
def get_base_dir() -> Path:
    return Path(__file__).resolve().parent.parent.parent

BASE_DIR = get_base_dir()
ENV_FILE = BASE_DIR / ".env"
LOGS_DIR = BASE_DIR / "logs"
CONFIG_DIR = BASE_DIR / "app" / "cfg"
DATA_DIR = BASE_DIR / "data"
# 新增：定义模型仓库（Zoo）的路径
MODEL_ZOO_DIR = DATA_DIR / "zoo"

FilePath = Annotated[Path, BeforeValidator(lambda v: Path(v) if isinstance(v, str) else v)]


# --- 配置模型定义 ---
class AppConfig(BaseModel):
    title: str = "烟火检测服务 (Hailo版)"
    description: str = "基于FastAPI和Hailo-8模型构建的实时烟火检测服务"
    version: str = "0.1.0"
    debug: bool = False
    stream_default_lifetime_minutes: int = Field(10, description="视频流默认生命周期（分钟），-1表示永久")
    stream_cleanup_interval_seconds: int = Field(60, description="后台清理过期视频流的运行间隔（秒）")
    stream_max_queue_size: int = Field(120, description="为视频流提供一个更充裕的缓冲区，以应对客户端网络抖动")
    max_concurrent_tasks: int = Field(2, ge=1, description="系统支持的最大并发视频流处理路数")


class ServerConfig(BaseModel):
    host: str = "0.0.0.0"
    port: int = 8000
    reload: bool = Field(False, description="是否开启热重载，仅建议在开发环境开启")


class LoggingConfig(BaseModel):
    level: str = "INFO"
    file_path: FilePath = LOGS_DIR / "app_hailo.log"
    max_bytes: int = 10 * 1024 * 1024
    backup_count: int = 5

    @model_validator(mode='after')
    def ensure_log_dir_exists(self) -> 'LoggingConfig':
        self.file_path.parent.mkdir(parents=True, exist_ok=True)
        return self


# 将 YoloConfig 重命名并修改为 HailoConfig
class HailoConfig(BaseModel):
    """Hailo模型与推理配置"""
    # 移除 onnx model_path 和 providers
    zoo_url: str = Field(
        default=f"file://{MODEL_ZOO_DIR.absolute()}",
        description="DeGirum 模型仓库的路径，建议使用本地文件路径以提高加载速度和稳定性。"
    )
    detection_model_name: str = Field(
        default="yolov8n_relu6_fire_smoke--640x640_quant_hailort_hailo8_1",
        description="要在模型仓库中加载的烟火检测模型的名称。"
    )
    class_names: List[str] = ["fire", "smoke"]
    confidence_threshold: float = Field(0.5, ge=0.0, le=1.0, description="目标检测置信度阈值")
    # IOU阈值通常在 DeGirum 模型内部或服务器端处理，这里可以保留用于后处理（如果需要）
    iou_threshold: float = Field(0.4, ge=0.0, le=1.0, description="非极大值抑制（NMS）的IOU阈值")

    @model_validator(mode='after')
    def ensure_zoo_dir_exists(self) -> 'HailoConfig':
        """验证后执行，确保模型仓库目录存在。"""
        # 确保目录存在，方便用户放置模型文件
        MODEL_ZOO_DIR.mkdir(parents=True, exist_ok=True)
        return self


# --- 主配置类 ---
class AppSettings(BaseSettings):
    app: AppConfig = Field(default_factory=AppConfig)
    server: ServerConfig = Field(default_factory=ServerConfig)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)
    hailo: HailoConfig = Field(default_factory=HailoConfig) # 重命名

    model_config = SettingsConfigDict(
        env_file=ENV_FILE,
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
        env_nested_delimiter="__",
    )

# --- YAML 配置加载器 (保持不变) ---
class ConfigLoader:
    @staticmethod
    def load_yaml_configs(env: Optional[str] = None) -> dict:
        current_env = env or os.getenv("APP_ENV", "development").lower()
        config: dict = {}
        default_path = CONFIG_DIR / "default.yaml"
        if default_path.exists():
            with open(default_path, "r", encoding="utf-8") as f:
                config = yaml.safe_load(f) or {}
        env_path = CONFIG_DIR / f"{current_env}.yaml"
        if env_path.exists():
            with open(env_path, "r", encoding="utf-8") as f:
                env_config = yaml.safe_load(f) or {}
                config = ConfigLoader._deep_merge_dicts(config, env_config)
        return config

    @staticmethod
    def _deep_merge_dicts(base: dict, updates: dict) -> dict:
        merged = base.copy()
        for key, value in updates.items():
            if isinstance(value, dict) and key in merged and isinstance(merged[key], dict):
                merged[key] = ConfigLoader._deep_merge_dicts(merged[key], value)
            else:
                merged[key] = value
        return merged

# --- 配置加载接口 (保持不变) ---
@lru_cache(maxsize=1)
def get_app_settings(env_override: Optional[str] = None) -> AppSettings:
    current_env = env_override or os.getenv("APP_ENV", "development")
    yaml_data = ConfigLoader.load_yaml_configs(current_env)
    settings_from_env = AppSettings()
    base_settings = AppSettings.model_validate(yaml_data)
    merged_data = ConfigLoader._deep_merge_dicts(
        base_settings.model_dump(),
        settings_from_env.model_dump(exclude_unset=True)
    )
    return AppSettings.model_validate(merged_data)