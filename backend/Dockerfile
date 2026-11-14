FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY renko_scalper ./renko_scalper
ENV RS_CONFIG=/config/config.yaml RS_DB=/data/signals.db PYTHONUNBUFFERED=1
VOLUME ["/data", "/config"]
EXPOSE 8787
CMD ["python", "-m", "renko_scalper", "serve"]
