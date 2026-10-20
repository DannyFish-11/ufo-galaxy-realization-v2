# ============================================================================
# Galaxy Agent 载体(跨设备整体方案阶段 5)—— 在容器里接中心派来的 Agent
#
# 在本仓库根目录构建、先配对、再常驻(配对码只能用一次,所以配对和常驻分两步):
#   docker build -f deploy/carrier/Dockerfile -t galaxy-carrier .
#   docker run --rm -v galaxy-carrier:/data galaxy-carrier --pair <配对码> --gateway http://<主脑>:<端口> --no-run
#   docker run -d --restart unless-stopped --name galaxy-carrier -v galaxy-carrier:/data galaxy-carrier
#
# 容器里没有 Docker,所以不接 run_code(代码只在沙箱里跑);文件读写(在 /data/work 里)、本机状态、
# 整段目标(推理加行动循环,模型经中心)照常。要跑代码就在宿主机上直接装载体(见 galaxy-carrier.service)。
# ============================================================================

# 换镜像源(比如国内镜像)时:--build-arg BASE_IMAGE=<镜像源>/python:3.11-slim
ARG BASE_IMAGE=python:3.11-slim
FROM ${BASE_IMAGE}

RUN pip install --no-cache-dir "websockets>=11.0" "pydantic>=2.9.0" \
    && useradd --uid 10001 --create-home carrier \
    && mkdir -p /data/work && chown -R carrier /data

WORKDIR /app
COPY core/ core/
COPY device_client/ device_client/

ENV PYTHONUNBUFFERED=1 \
    GALAXY_DEVICE_STATE=/data/carrier.json \
    GALAXY_CARRIER_WORKDIR=/data/work

USER carrier
VOLUME ["/data"]
ENTRYPOINT ["python", "-m", "device_client", "--carrier"]
