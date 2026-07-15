FROM python:3.12-slim

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends git \
    && pip install --no-cache-dir "git+https://github.com/cfdude/mcp-finnhub.git@b7a2651b88efa7807b8d2486f0a736f51fd33332" \
    && apt-get purge -y --auto-remove git \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /data/finnhub
ENV FINNHUB_STORAGE_DIR=/data/finnhub

EXPOSE 8125

CMD ["mcp-finnhub", "--transport", "http", "--host", "0.0.0.0", "--port", "8125"]
