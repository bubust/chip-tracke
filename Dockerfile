FROM python:3.12-slim
# 台灣時間：程式裡的 datetime.now() / date.today()（盤中判斷、今日日期）都以台灣時間為準
ENV TZ=Asia/Taipei
RUN apt-get update && apt-get install -y --no-install-recommends tzdata \
    && ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
CMD exec uvicorn server:app --host 0.0.0.0 --port ${PORT:-8080}
