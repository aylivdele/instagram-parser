FROM python:3.11-slim

# Системные зависимости (curl нужен для healthcheck)
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Устанавливаем зависимости отдельным слоем (кэшируется при неизменном requirements.txt)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Копируем исходники
COPY instagram_monitor.py .
COPY api_server.py .

# Создаём точку монтирования для базы данных
RUN mkdir -p /data

# Запускаем Flask через gunicorn (production-ready)
# --workers 1 — важно! фоновый поток мониторинга не должен дублироваться
CMD ["gunicorn", \
     "--bind", "0.0.0.0:5000", \
     "--workers", "1", \
     "--threads", "4", \
     "--timeout", "120", \
     "--access-logfile", "-", \
     "--error-logfile", "-", \
     "api_server:app"]
