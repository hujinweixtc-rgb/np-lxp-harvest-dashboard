FROM python:3.13-slim

# 容器默认 UTC，而 DMS 管线用 date.today() 划分日期桶、拼接口区间；
# 必须固定为北京时间，否则北京时间凌晨刷新会取到前一天。
RUN apt-get update \
 && apt-get install -y --no-install-recommends tzdata \
 && ln -snf /usr/share/zoneinfo/Asia/Shanghai /etc/localtime \
 && printf 'Asia/Shanghai\n' > /etc/timezone \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    TZ=Asia/Shanghai \
    DASH_RAW_DIR=/tmp/raw \
    DASH_DATA_DIR=/tmp/data

# 服务代码 + DMS 管线（管线只依赖标准库，无需 pip 安装）
COPY server/ ./server/
COPY scripts/ ./scripts/

# 前端与数据快照
COPY index.html ./index.html
COPY data/ ./data/

# DMS 原始缓存（容器启动时解压到 /tmp/raw）
COPY raw.tar.gz ./raw.tar.gz

EXPOSE 8080
CMD ["python", "server/app.py"]
