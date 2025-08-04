# app/router/device_router.py
from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field
from typing import List, Optional, TypeVar, Generic
import asyncio
from app.cfg.logging import app_logger

# --- 通用 API 响应模型 ---
T = TypeVar("T")


class ApiResponse(BaseModel, Generic[T]):
    """标准化的API响应体结构。"""
    code: int = Field(0, description="响应状态码，0表示成功，其它非零值表示特定的业务失败")
    msg: str = Field("Success", description="响应消息，提供操作结果的文本描述")
    data: Optional[T] = Field(None, description="实际的响应数据。")


# --- Hailo 设备信息 Schema ---

class TemperatureInfo(BaseModel):
    """芯片内部温度传感器的读数。"""
    ts0_celsius: Optional[float] = Field(None, description="温度传感器 TS0 的读数（摄氏度）")
    ts1_celsius: Optional[float] = Field(None, description="温度传感器 TS1 的读数（摄-氏度）")


class DeviceInfo(BaseModel):
    """单个 Hailo 设备的详细信息，包含了静态和动态指标。"""
    device_id: str = Field(..., description="设备在系统中的唯一标识符 (例如 PCIe 地址)")
    board_name: Optional[str] = Field(None, description="AI 芯片的型号名称")
    serial_number: Optional[str] = Field(None, description="硬件模块的唯一序列号")
    part_number: Optional[str] = Field(None, description="制造商的部件号")
    product_name: Optional[str] = Field(None, description="产品的详细描述名称")
    device_architecture: Optional[str] = Field(None, description="硬件核心架构")
    nn_core_clock_rate_mhz: Optional[float] = Field(None, description="神经网络核心的运行频率 (MHz)")
    boot_source: Optional[str] = Field(None, description="设备固件的启动来源 (例如 PCIE)")

    # --- 字段名称和描述已更新 ---
    current_power_watts: Optional[float] = Field(None, description="当前瞬时功耗（瓦特）")
    chip_temperature: Optional[TemperatureInfo] = Field(None, description="芯片内部温度（摄氏度）")


class GetAllDevicesResponseData(BaseModel):
    """获取所有 Hailo 设备信息的响应数据。"""
    device_count: int = Field(..., description="检测到的 Hailo 设备总数")
    devices: List[DeviceInfo] = Field([], description="所有 Hailo 设备的详细信息列表")


router = APIRouter()


@router.get(
    "/device",
    response_model=ApiResponse[GetAllDevicesResponseData],
    summary="获取所有 Hailo 设备的详细信息",
    description="获取所有连接的 Hailo 设备的静态信息（如型号、序列号）和动态状态（如瞬时功耗、温度）。",
    tags=["Hailo设备"]
)
async def get_hailo_devices():
    """返回所有 Hailo 设备的详细信息，包括静态硬件参数和实时动态数据。"""
    device_list: List[DeviceInfo] = []
    try:
        from hailo_platform import Device, HailoRTException
        from hailo_platform.pyhailort.pyhailort import BoardInformation

        def _scan_and_get_info_sync():
            """同步函数，用于在单独的线程中执行所有阻塞的 Hailo API 调用。"""
            device_infos = Device.scan()
            if not device_infos:
                return []

            targets = [Device(di) for di in device_infos]
            results = []

            for di, target in zip(device_infos, targets):
                static_info = {}
                dynamic_info = {}

                try:
                    board_info = target.control.identify()
                    extended_info = target.control.get_extended_device_information()
                    static_info = {
                        "board_name": board_info.board_name,
                        "serial_number": board_info.serial_number,
                        "part_number": board_info.part_number,
                        "product_name": board_info.product_name,
                        "device_architecture": BoardInformation.get_hw_arch_str(board_info.device_architecture),
                        "nn_core_clock_rate_mhz": round(extended_info.neural_network_core_clock_rate / 1_000_000, 1),
                        "boot_source": str(extended_info.boot_source).split('.')[-1],
                    }

                    # 获取当前瞬时功耗
                    current_power = target.control.power_measurement()  #
                    temp_data = target.control.get_chip_temperature()

                    dynamic_info = {
                        "current_power_watts": round(current_power, 3) if current_power is not None else None,
                        "chip_temperature": TemperatureInfo(
                            ts0_celsius=temp_data.ts0_temperature,
                            ts1_celsius=temp_data.ts1_temperature
                        ),
                    }

                except HailoRTException as e:
                    app_logger.warning(f"获取设备 {di} 的部分信息失败: {e}")
                except Exception as e:
                    app_logger.error(f"获取设备 {di} 信息时发生未知错误: {e}")

                results.append(
                    DeviceInfo(
                        device_id=str(di),
                        **static_info,
                        **dynamic_info
                    )
                )


            return results

        device_list = await asyncio.to_thread(_scan_and_get_info_sync)

    except ImportError:
        app_logger.error("Hailo 平台库未安装或环境未激活。")
        return ApiResponse(
            code=500,
            msg="服务器内部错误：Hailo 平台库不可用。",
            data=GetAllDevicesResponseData(device_count=0, devices=[])
        )
    except Exception as e:
        app_logger.error(f"获取 Hailo 设备信息时发生未预期的错误: {e}", exc_info=True)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"获取设备信息失败: {e}")

    return ApiResponse(
        data=GetAllDevicesResponseData(
            device_count=len(device_list),
            devices=device_list
        )
    )