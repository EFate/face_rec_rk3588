# run.py
import os
import socket
from typing import Optional

import typer
import uvicorn
from dotenv import load_dotenv

from app.cfg.config import get_app_settings, AppSettings, BASE_DIR
from app.cfg.logging import app_logger as logger, setup_logging

load_dotenv()

# 使用 Typer 创建一个优雅的命令行接口 (CLI)
app = typer.Typer(
    pretty_exceptions_enable=False,  # 禁用Typer的异常美化，以便看到完整的FastAPI堆栈跟踪
    context_settings={"help_option_names": ["-h", "--help"]},
)


def init_app_state(env: Optional[str] = None) -> AppSettings:
    """
    初始化应用状态：设置环境变量，加载配置，并配置日志。
    这是在任何命令运行之前都需要执行的步骤。
    """
    if env:
        os.environ["APP_ENV"] = env

    # 清理 lru_cache，确保每次调用CLI时都能根据最新的--env标志重新加载配置
    get_app_settings.cache_clear()
    current_settings = get_app_settings()
    # 根据加载的最新配置来设置日志系统
    setup_logging(current_settings)

    logger.info(f"⚙️  应用环境已确立: {os.getenv('APP_ENV', 'development').upper()}")
    return current_settings


def get_local_ip() -> str:
    """获取本机在局域网中的IP地址，用于在日志中提供方便访问的URL。"""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            # 连接到一个公共DNS服务器（不会真的发送数据）来确定出口IP
            s.connect(("8.8.8.8", 80))
            return s.getsockname()[0]
    except Exception:
        return "127.0.0.1"


@app.callback(invoke_without_command=True)
def main(
        ctx: typer.Context,
        env: Optional[str] = typer.Option(
            None, "--env", "-e",
            help="指定运行环境 (例如 'development', 'production')。会加载对应的 a.yaml 文件。",
            envvar="APP_ENV",  # 也可以通过环境变量 APP_ENV 设置
            show_envvar=True
        ),
        version: bool = typer.Option(
            False, "--version", "-v",
            help="显示应用版本信息并退出。"
        ),
):
    """
    高性能烟火检测服务 - 命令行接口。

    使用 'start' 命令来启动服务。
    """
    settings = init_app_state(env)
    # 将加载的配置存储在上下文中，以便子命令可以访问
    ctx.obj = settings

    if version:
        typer.echo(f"{settings.app.title} - Version: {settings.app.version}")
        raise typer.Exit()

    # 如果没有调用任何子命令（如 'start'），则显示帮助信息
    if ctx.invoked_subcommand is None:
        typer.echo("未指定子命令。请使用 'start' 来启动服务。")
        typer.echo("使用 'python run.py --help' 查看所有可用命令。")


@app.command(name="start")
def start_server(
        ctx: typer.Context,
        host: Optional[str] = typer.Option(None, "--host", help="覆盖配置文件中的服务器主机。"),
        port: Optional[int] = typer.Option(None, "--port", help="覆盖配置文件中的服务器端口。"),
):
    """
    启动 FastAPI Uvicorn 服务器。
    """
    settings: AppSettings = ctx.obj

    # 优先使用命令行参数，否则使用配置文件中的值
    final_host = host if host is not None else settings.server.host
    final_port = port if port is not None else settings.server.port
    final_reload = settings.server.reload
    is_dev_mode = (os.getenv("APP_ENV", "development").lower() == "development")

    logger.info(f"\n🚀 准备启动服务器: {settings.app.title} v{settings.app.version}")
    logger.info(f"  - 监听地址: http://{final_host}:{final_port}")
    if final_host == "0.0.0.0":
        local_ip = get_local_ip()
        logger.info(f"  - 本机访问: http://127.0.0.1:{final_port}")
        logger.info(f"  - 局域网访问: http://{local_ip}:{final_port}")
    logger.info(f"  - API 文档: http://127.0.0.1:{final_port}/docs")
    logger.info(f"  - 热重载模式: {'✅ 开启' if final_reload and is_dev_mode else '❌ 关闭'}")
    if final_reload and not is_dev_mode:
        logger.warning("  - 警告: 热重载在非开发环境中被请求，但通常不建议这样做。")

    try:
        uvicorn.run(
            "app.main:app",
            host=final_host,
            port=final_port,
            reload=final_reload and is_dev_mode,  # 仅在开发模式下真正启用热重载
            log_level=settings.logging.level.lower(),
            log_config=None,  # 设置为 None，因为 Loguru 已完全接管日志
            app_dir=str(BASE_DIR) if final_reload else None,  # 在热重载时指定项目根目录
        )
    except Exception as e:
        logger.critical(f"⚠️ Uvicorn 服务器启动失败: {e}", exc_info=True)
        raise typer.Exit(code=1)


if __name__ == "__main__":
    app()