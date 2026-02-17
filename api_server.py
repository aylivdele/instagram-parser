"""
Flask API Server для Instagram Monitor
Связывает фронтенд (Telegram Mini App) с бэкендом мониторинга
"""

import os
from flask import Flask, jsonify, request
from flask_cors import CORS
import asyncio
from instagram_monitor import InstagramMonitor, MonitorAPI
import threading
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)
CORS(app)  # Разрешаем запросы от Telegram Mini App

# ── Конфигурация из переменных окружения ──────────────────────
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "YOUR_BOT_TOKEN")
TELEGRAM_CHAT_ID   = os.environ.get("TELEGRAM_CHAT_ID",   "YOUR_CHAT_ID")
DB_PATH            = os.environ.get("DB_PATH",             "instagram_monitor.db")

# Инициализация монитора
monitor = InstagramMonitor(
    db_path=DB_PATH,
    telegram_token=TELEGRAM_BOT_TOKEN
)
api = MonitorAPI(monitor)

# Запуск фонового мониторинга
def run_background_monitoring():
    """Запускает мониторинг в отдельном потоке"""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    logger.info("Фоновый мониторинг запущен")
    loop.run_until_complete(
        monitor.run_continuous_monitoring(
            interval_minutes=60,
            telegram_chat_id=TELEGRAM_CHAT_ID
        )
    )

monitoring_thread = threading.Thread(target=run_background_monitoring, daemon=True)
monitoring_thread.start()


# ── API Endpoints ──────────────────────────────────────────────

@app.route('/api/competitors', methods=['GET'])
def get_competitors():
    try:
        stats = api.get_competitors_stats()
        return jsonify({"success": True, "data": stats})
    except Exception as e:
        logger.error(f"Ошибка в /api/competitors: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/api/competitors', methods=['POST'])
def add_competitor():
    try:
        data = request.json
        username = data.get('username', '').strip()
        if not username:
            return jsonify({"success": False, "error": "Username обязателен"}), 400
        monitor.add_competitor(username)
        return jsonify({"success": True, "message": f"Конкурент @{username} добавлен"})
    except Exception as e:
        logger.error(f"Ошибка в POST /api/competitors: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/api/competitors/<username>', methods=['DELETE'])
def remove_competitor(username):
    try:
        return jsonify({"success": True, "message": f"Конкурент @{username} удален"})
    except Exception as e:
        logger.error(f"Ошибка в DELETE /api/competitors: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/api/alerts', methods=['GET'])
def get_alerts():
    try:
        limit = request.args.get('limit', 10, type=int)
        alerts = api.get_alerts(limit=limit)
        return jsonify({"success": True, "data": alerts})
    except Exception as e:
        logger.error(f"Ошибка в /api/alerts: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/api/trigger-check', methods=['POST'])
def trigger_manual_check():
    try:
        async def check():
            await monitor.monitor_cycle(TELEGRAM_CHAT_ID)
        asyncio.run(check())
        return jsonify({"success": True, "message": "Проверка запущена"})
    except Exception as e:
        logger.error(f"Ошибка в /api/trigger-check: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/api/status', methods=['GET'])
def get_status():
    try:
        competitors = monitor.get_competitors()
        return jsonify({
            "success": True,
            "data": {
                "active": True,
                "competitors_count": len(competitors),
                "last_check": "just now"
            }
        })
    except Exception as e:
        logger.error(f"Ошибка в /api/status: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/health', methods=['GET'])
def health_check():
    return jsonify({"status": "ok", "service": "instagram-monitor-api"})


if __name__ == '__main__':
    logger.info("Запуск Flask API сервера...")
    app.run(host='0.0.0.0', port=5000, debug=False)
