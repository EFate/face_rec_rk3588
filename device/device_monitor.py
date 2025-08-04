#!/usr/bin/env python3

import json
import time
import sys
import os
from pathlib import Path
import logging

# --- 配置区 ---
# 1. 从环境变量获取路径，如果未设置，则使用默认值
DEFAULT_OUTPUT_PATH = "/data/hailo/hailo_device_status.json"
OUTPUT_FILE_PATH = Path(os.getenv("DEVICE_INFO_FILE_PATH", DEFAULT_OUTPUT_PATH))

# 监控的时间间隔（秒）
MONITORING_INTERVAL_SECONDS = 5

# --- 日志配置 ---
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    stream=sys.stdout
)
app_logger = logging.getLogger(__name__)


try:
    from hailo_platform import Device, HailoRTException
    from hailo_platform.pyhailort.pyhailort import BoardInformation
except ImportError:
    app_logger.critical("❌ 无法导入 'hailo_platform' 模块。")
    app_logger.critical("请确保您已激活正确的Python虚拟环境（例如 'pyhailort' 或 'TAPPAS'）。")
    sys.exit(1)


def fetch_device_metrics() -> dict:
    """
    扫描并获取所有Hailo设备的详细指标。
    """
    device_infos = Device.scan()
    if not device_infos:
        app_logger.warning("未检测到 Hailo 设备。")
        return {"device_count": 0, "devices": []}

    targets = [Device(di) for di in device_infos]
    results = []

    for di, target in zip(device_infos, targets):
        device_data = {"device_id": str(di)}
        try:
            # 获取静态信息
            board_info = target.control.identify()
            extended_info = target.control.get_extended_device_information()

            # 清理从C语言结构体中读取的字符串末尾的空字符
            device_data.update({
                "board_name": board_info.board_name.strip('\x00'),
                "serial_number": board_info.serial_number.strip('\x00'),
                "part_number": board_info.part_number.strip('\x00'),
                "product_name": board_info.product_name.strip('\x00'),
                "device_architecture": BoardInformation.get_hw_arch_str(board_info.device_architecture),
                "nn_core_clock_rate_mhz": round(extended_info.neural_network_core_clock_rate / 1_000_000, 1),
                "boot_source": str(extended_info.boot_source).split('.')[-1],
            })

            # 获取动态信息（瞬时功耗和温度）
            current_power = target.control.power_measurement()
            temp_data = target.control.get_chip_temperature()

            device_data.update({
                "current_power_watts": round(current_power, 3) if current_power is not None else None,
                "chip_temperature": {
                    "ts0_celsius": temp_data.ts0_temperature,
                    "ts1_celsius": temp_data.ts1_temperature
                },
            })

        except HailoRTException as e:
            app_logger.warning(f"获取设备 {di} 的部分信息失败: {e}")
        except Exception as e:
            app_logger.error(f"获取设备 {di} 信息时发生未知错误: {e}")

        results.append(device_data)

    return {"device_count": len(results), "devices": results}


def main_loop():
    """
    主循环，周期性地执行监控和文件写入任务。
    """
    # 2. 自动创建目录
    try:
        OUTPUT_FILE_PATH.parent.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        app_logger.critical(f"❌ 无法创建输出目录 {OUTPUT_FILE_PATH.parent}: {e}")
        sys.exit(1)

    app_logger.info("🚀 Hailo 设备监控服务已启动。")
    app_logger.info(f"每隔 {MONITORING_INTERVAL_SECONDS} 秒将向文件 '{OUTPUT_FILE_PATH.absolute()}' 写入一次状态。")
    app_logger.info("按 Ctrl+C 停止服务。")

    try:
        while True:
            metrics_data = fetch_device_metrics()
            try:
                with open(OUTPUT_FILE_PATH, 'w', encoding='utf-8') as f:
                    json.dump(metrics_data, f, indent=2, ensure_ascii=False)
                app_logger.info(f"✅ 已成功将 {metrics_data['device_count']} 个设备的状态更新到 {OUTPUT_FILE_PATH}")
            except IOError as e:
                app_logger.error(f"❌ 写入文件失败: {e}")

            time.sleep(MONITORING_INTERVAL_SECONDS)

    except KeyboardInterrupt:
        app_logger.info("\n👋 收到用户中断 (Ctrl+C)，服务正在停止。")
    except Exception as e:
        app_logger.critical(f"发生严重错误，服务意外终止: {e}", exc_info=True)
    finally:
        app_logger.info("服务已关闭。")


if __name__ == "__main__":
    main_loop()