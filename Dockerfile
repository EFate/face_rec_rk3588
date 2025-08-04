# Dockerfile

# --- Stage 1: 基础镜像 ---
FROM swr.cn-north-4.myhuaweicloud.com/ddn-k8s/docker.io/python:3.10-slim

# --- Stage 2: 配置国内软件源 (清华源) ---
RUN rm -f /etc/apt/sources.list && \
    rm -rf /etc/apt/sources.list.d/* && \
    rm -rf /etc/apt/apt.conf.d/* && \
    echo "deb http://mirrors.tuna.tsinghua.edu.cn/debian/ bookworm main contrib non-free non-free-firmware" > /etc/apt/sources.list && \
    echo "deb http://mirrors.tuna.tsinghua.edu.cn/debian/ bookworm-updates main contrib non-free non-free-firmware" >> /etc/apt/sources.list && \
    echo "deb http://mirrors.tuna.tsinghua.edu.cn/debian/ bookworm-backports main contrib non-free non-free-firmware" >> /etc/apt/sources.list && \
    echo "deb http://mirrors.tuna.tsinghua.edu.cn/debian-security bookworm-security main contrib non-free non-free-firmware" >> /etc/apt/sources.list && \
    cat <<EOF > /etc/apt/apt.conf.d/99verify-peer.conf
Acquire::https::mirrors.tuna.tsinghua.edu.cn::Verify-Peer "false";
Acquire::https::mirrors.tuna.tsinghua.edu.cn::Verify-Host "false";
EOF

# 配置 pip
RUN pip config set global.index-url https://pypi.tuna.tsinghua.edu.cn/simple && \
    pip config set install.trusted-host pypi.tuna.tsinghua.edu.cn && \
    pip install --no-cache-dir --upgrade pip

# --- Stage 3: 安装系统依赖 ---
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        build-essential \
        libgl1-mesa-glx \
        libglib2.0-0 && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# --- Stage 4: 安装 RK3588 RKNN 用户态运行时 ---
# 该步骤用于克隆 RKNN 工具包并安装其 aarch64 架构的运行时库
WORKDIR /app
RUN apt-get update && \
    apt-get install -y git && \
    git clone https://github.com/Pelochus/ezrknn-toolkit2 && \
    cd ezrknn-toolkit2 && \
    git checkout 99db9e5b950ccc7e0d1ee20a16b92f7d8b6e60e6 && \
    cp ./rknpu2/runtime/Linux/librknn_api/aarch64/librknnrt.so /usr/lib/ && \
    cd .. && \
    apt-get remove -y git && \
    rm -rf ezrknn-toolkit2 && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# --- Stage 5: 安装项目依赖并拷贝代码 ---
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
RUN chmod +x start.sh

# --- Stage 6: 配置容器运行 ---
EXPOSE 12020
EXPOSE 12021
CMD ["./start.sh"]