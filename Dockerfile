FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    HOST=0.0.0.0 \
    PORT=8000 \
    FINBRIDGE_DB_PATH=/app/storage/runtime.sqlite3

WORKDIR /app
COPY requirements-web.txt ./
RUN python -m pip install --no-cache-dir -r requirements-web.txt

COPY web_app.py ./
COPY src/ ./src/
COPY web/ ./web/
COPY data/ ./data/
COPY output/真实企业案例/ ./output/真实企业案例/

RUN useradd --create-home --uid 10001 agent \
    && mkdir -p /app/storage \
    && chown -R agent:agent /app
USER agent

EXPOSE 8000
CMD ["python", "web_app.py"]
