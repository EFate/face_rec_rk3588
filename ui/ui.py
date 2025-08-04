# ui.py
import os

import streamlit as st
import requests
import json
from datetime import datetime
from typing import Tuple, Any

# ==============================================================================
# 1. 页面配置与美化 (Page Config & Styling)
# ==============================================================================

st.set_page_config(
    page_title="AI烟火安全监测平台",
    page_icon="🔥",
    layout="wide",
    initial_sidebar_state="expanded"
)

# --- 沿用并微调的CSS样式 ---
st.markdown("""
<style>
    .stApp { background-color: #f0f2f6; }
    h1, h2, h3 { font-weight: 700; color: #1a1f36; }
    [data-testid="stSidebar"] {
        background-color: #ffffff;
        border-right: 1px solid #e0e4e8;
    }
    [data-testid="stRadio"] > div[role="radiogroup"] > label > div:first-child { display: none; }
    [data-testid="stRadio"] > div[role="radiogroup"] {
        display: flex; flex-direction: row; gap: 1.5rem; border-bottom: 2px solid #dee2e6;
        padding-bottom: 0; margin-bottom: 1.5rem;
    }
    [data-testid="stRadio"] > div[role="radiogroup"] > label {
        height: 50px; padding: 0 1rem; background-color: transparent;
        border-bottom: 4px solid transparent; border-radius: 0;
        font-weight: 600; color: #6c757d; transition: all 0.2s ease-in-out;
        cursor: pointer; margin: 0;
    }
    [data-testid="stRadio"] > div[role="radiogroup"] > label[data-baseweb="radio"]:has(input:checked) {
        border-bottom: 4px solid #d9534f; /* 警告红色 */
        color: #d9534f;
    }
    .info-card {
        background-color: #ffffff; border-radius: 12px; padding: 25px;
        border: 1px solid #e0e4e8; box-shadow: 0 4px 12px rgba(0,0,0,0.05);
        text-align: center; transition: transform 0.2s ease; height: 100%;
    }
    .info-card:hover { transform: translateY(-5px); }
    .info-card .icon { font-size: 2.5rem; }
    .info-card .title { font-weight: 600; color: #6c757d; font-size: 1rem; margin-top: 10px; }
    .info-card .value { font-weight: 700; color: #1a1f36; font-size: 2rem; }
</style>
""", unsafe_allow_html=True)


# ==============================================================================
# 2. 会话状态管理 (Session State Management)
# ==============================================================================

def initialize_session_state():
    """初始化应用所需的会话状态。"""
    backend_host = os.getenv("HOST__IP", "localhost")
    backend_port = os.getenv("SERVER__PORT", "12020")
    defaults = {
        "api_url": f"{backend_host}:{backend_port}",  # 默认指向后端服务
        "api_status": (False, "尚未连接"),
        "active_page": "系统状态",
        "viewing_stream_info": None,
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


# ==============================================================================
# 3. API通信与数据处理 (API Communication & Data Handling)
# ==============================================================================

API_ENDPOINTS = {
    'HEALTH': '/api/detection/health',
    'STREAMS_START': '/api/detection/streams/start',
    'STREAMS_STOP': '/api/detection/streams/stop/{}',
    'STREAMS_LIST': '/api/detection/streams',
}


@st.cache_data(ttl=10)
def check_api_status(api_url: str) -> Tuple[bool, str]:
    """检查后端API的健康状况。"""
    try:
        url = f"http://{api_url}{API_ENDPOINTS['HEALTH']}"
        response = requests.get(url, timeout=3)
        if response.ok and response.json().get("code") == 0:
            return True, response.json().get("data", {}).get("message", "服务运行正常")
        return False, f"服务异常 (HTTP: {response.status_code})"
    except requests.RequestException:
        return False, "服务连接失败"


def api_request(method: str, endpoint: str, **kwargs) -> Tuple[bool, Any, str]:
    """统一的API请求函数。"""
    full_url = f"http://{st.session_state.api_url}{endpoint}"
    try:
        response = requests.request(method, full_url, timeout=10, **kwargs)
        if response.ok:
            if response.status_code == 204 or not response.content:
                return True, None, "操作成功"
            res_json = response.json()
            if res_json.get("code") == 0:
                return True, res_json.get("data"), res_json.get("msg", "操作成功")
            else:
                return False, None, res_json.get("msg", "发生未知错误")
        else:
            try:
                error_msg = response.json().get("detail", response.text)
            except json.JSONDecodeError:
                error_msg = f"无法解析响应 (HTTP {response.status_code})"
            return False, None, error_msg
    except requests.RequestException as e:
        return False, None, f"网络请求失败: {e}"


def format_datetime_human(dt_str: str) -> str:
    """将ISO格式的日期时间字符串转换为人性化的格式"""
    if not dt_str:
        return "永久"
    try:
        dt_obj = datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
        return dt_obj.strftime("%Y-%m-%d %H:%M:%S")
    except (ValueError, TypeError):
        return "N/A"


# ==============================================================================
# 4. UI渲染模块 (UI Rendering Modules)
# ==============================================================================

def render_sidebar():
    """渲染侧边栏。"""
    with st.sidebar:
        st.title("🔥 AI烟火安全监测系统")
        st.caption("v1.0.0")

        st.session_state.api_url = st.text_input(
            "后端服务地址",
            value=st.session_state.api_url,
            help="例如: 127.0.0.1:8000"
        )

        is_connected, status_msg = check_api_status(st.session_state.api_url)
        st.session_state.api_status = (is_connected, status_msg)
        status_icon = "✅" if is_connected else "❌"
        st.info(f"**API状态:** {status_msg}", icon=status_icon)

        st.divider()
        st.info("© 2025 AI安全监测平台")


def render_status_page():
    """渲染仪表盘/系统状态页面。"""
    st.header("📊 系统状态总览")

    is_connected, _ = st.session_state.api_status
    if not is_connected:
        st.warning("API服务未连接，请在左侧侧边栏配置正确的服务地址并确保后端服务已启动。")
        return

    # 刷新按钮
    if st.button("刷新统计信息", type="primary"):
        st.cache_data.clear()

    # 获取视频流数量
    success, stream_data, _ = api_request("GET", API_ENDPOINTS['STREAMS_LIST'])
    stream_count = stream_data.get('active_streams_count', 0) if success else "N/A"
    api_status, api_color = ("在线", "#28a745") if st.session_state.api_status[0] else ("离线", "#dc3545")

    col1, col2, col3 = st.columns(3)
    with col1:
        st.html(f"""
        <div class="info-card">
            <div class="icon">📹</div>
            <div class="title">当前活动监测流</div>
            <div class="value">{stream_count}</div>
        </div>""")
    with col2:
        st.html(f"""
        <div class="info-card">
            <div class="icon">📡</div>
            <div class="title">API服务状态</div>
            <div class="value" style="color:{api_color};">{api_status}</div>
        </div>""")
    with col3:
        st.html(f"""
        <div class="info-card">
            <div class="icon">🔥</div>
            <div class="title">核心监测目标</div>
            <div class="value" style="font-size: 1.5rem;">Smoke & Fire</div>
        </div>""")

    st.divider()
    st.info("请切换到 **实时监测** 页面来启动和管理视频流。", icon="👉")


def render_monitoring_page():
    """渲染实时视频监控页面。"""
    st.header("🛰️ 实时视频监测")

    with st.expander("▶️ 启动新监测任务", expanded=True):
        with st.form("start_stream_form"):
            source = st.text_input("视频源", "0", help="可以是摄像头ID(如 0, 1) 或 视频文件/URL")
            lifetime = st.number_input("生命周期(分钟)", min_value=-1, value=10, help="-1 代表永久")
            if st.form_submit_button("🚀 开启监测", use_container_width=True, type="primary"):
                with st.spinner("正在请求启动视频流..."):
                    payload = {"source": source, "lifetime_minutes": lifetime}
                    success, data, msg = api_request('POST', API_ENDPOINTS['STREAMS_START'], json=payload)
                if success and data:
                    st.toast(f"视频流任务已启动！ID: ...{data['stream_id'][-6:]}", icon="🚀")
                    st.session_state.viewing_stream_info = data
                    st.rerun()
                else:
                    st.error(f"启动失败: {msg}")

    # 显示当前正在观看的视频流
    if st.session_state.get("viewing_stream_info"):
        stream_info = st.session_state.viewing_stream_info
        st.subheader(f"正在播放: `{stream_info['source']}`")
        st.caption(f"Stream ID: `{stream_info['stream_id']}`")
        st.image(stream_info['feed_url'], caption=f"实时视频流 | 源: {stream_info['source']}")
    else:
        st.info("当前未选择任何视频流进行观看。请从下面的列表中选择一个，或启动一个新的监测任务。")

    st.divider()

    # 获取并显示所有活动的视频流列表
    st.subheader("所有活动中的监测任务")
    if st.button("刷新流列表"):
        st.cache_data.clear()
        st.rerun()

    success, data, msg = api_request("GET", API_ENDPOINTS['STREAMS_LIST'])
    if not success:
        st.error(f"无法获取活动流列表: {msg}")
        return

    active_streams = data.get('streams', [])
    if not active_streams:
        st.info("目前没有正在运行的视频监测任务。")
    else:
        for stream in active_streams:
            stream_id = stream['stream_id']
            with st.container(border=True):
                col1, col2 = st.columns([3, 1])
                with col1:
                    st.markdown(f"**来源:** `{stream['source']}`")
                    st.caption(
                        f"ID: `{stream_id}` | 启动于: {format_datetime_human(stream.get('started_at'))} | 将过期: {format_datetime_human(stream.get('expires_at'))}")
                with col2:
                    b_col1, b_col2 = st.columns(2)
                    if b_col1.button("👁️", key=f"view_{stream_id}", help="观看此流", use_container_width=True):
                        st.session_state.viewing_stream_info = stream
                        st.rerun()
                    if b_col2.button("⏹️", key=f"stop_{stream_id}", help="停止此流", type="primary",
                                     use_container_width=True):
                        with st.spinner(f"正在停止流 {stream['source']}..."):
                            endpoint = API_ENDPOINTS['STREAMS_STOP'].format(stream_id)
                            stop_success, _, stop_msg = api_request('POST', endpoint)
                        if stop_success:
                            st.toast(f"视频流 {stream['source']} 已停止。", icon="✅")
                            if st.session_state.viewing_stream_info and st.session_state.viewing_stream_info[
                                'stream_id'] == stream_id:
                                st.session_state.viewing_stream_info = None
                            st.rerun()
                        else:
                            st.error(f"停止失败: {stop_msg}")


# ==============================================================================
# 5. 主程序入口 (Main Application Entrypoint)
# ==============================================================================
def main():
    """主应用函数。"""
    initialize_session_state()
    render_sidebar()

    pages = ["系统状态", "实时监测"]
    st.session_state.active_page = st.radio(
        "主导航",
        options=pages,
        key="page_selector",
        label_visibility="collapsed",
        horizontal=True,
    )

    if st.session_state.active_page == "系统状态":
        render_status_page()
    elif st.session_state.active_page == "实时监测":
        render_monitoring_page()


if __name__ == "__main__":
    main()