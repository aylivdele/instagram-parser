"""
Flask API Server для Instagram Monitor
Мультипользовательская версия
"""

import os
from flask import Flask, jsonify, request
from flask_cors import CORS
import asyncio
from instagram_monitor import InstagramMonitor, MonitorAPI, Config
import threading
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)
CORS(app)

# Инициализация монитора
monitor = InstagramMonitor()
api = MonitorAPI(monitor)

# Запуск фонового мониторинга
def run_background_monitoring():
    """Запускает мониторинг в отдельном потоке"""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    
    Config.log_config()
    logger.info("Фоновый мониторинг запущен")
    loop.run_until_complete(monitor.run_continuous_monitoring())

monitoring_thread = threading.Thread(target=run_background_monitoring, daemon=True)
monitoring_thread.start()


# ══════════════════════════════════════════════════════════════════
# Хелперы
# ══════════════════════════════════════════════════════════════════

def get_user_id(request) -> str:
    """
    Извлекает user_id из запроса.
    
    Поддерживаемые источники (приоритет):
    1. Header X-User-Id
    2. Query параметр user_id
    3. JSON body {"user_id": "..."}
    4. Для Telegram Mini App: можно парсить initData
    """
    # Header (рекомендуемый способ)
    user_id = request.headers.get('X-User-Id')
    if user_id:
        return user_id
    
    # Query параметр
    user_id = request.args.get('user_id')
    if user_id:
        return user_id
    
    # JSON body
    if request.is_json:
        user_id = request.json.get('user_id')
        if user_id:
            return user_id
    
    # Для Telegram Mini App можно парсить Telegram.WebApp.initDataUnsafe.user.id
    # но это требует валидации на сервере
    
    return None


# ══════════════════════════════════════════════════════════════════
# API Endpoints
# ══════════════════════════════════════════════════════════════════

@app.route('/api/register', methods=['POST'])
def register_user():
    """
    Регистрация/обновление пользователя
    
    Body: {
        "user_id": "telegram_123456",
        "telegram_chat_id": "123456"  // опционально
    }
    """
    try:
        data = request.json
        user_id = data.get('user_id')
        telegram_chat_id = data.get('telegram_chat_id')
        
        if not user_id:
            return jsonify({"success": False, "error": "user_id обязателен"}), 400
        
        monitor.register_user(user_id, telegram_chat_id)
        
        return jsonify({
            "success": True,
            "message": "Пользователь зарегистрирован"
        })
    except Exception as e:
        logger.error(f"Ошибка в /api/register: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/api/competitors', methods=['GET'])
def get_competitors():
    """Получить список конкурентов пользователя"""
    try:
        user_id = get_user_id(request)
        if not user_id:
            return jsonify({"success": False, "error": "user_id не указан"}), 401
        
        stats = api.get_competitors_stats(user_id)
        return jsonify({"success": True, "data": stats})
    except Exception as e:
        logger.error(f"Ошибка в /api/competitors: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/api/competitors', methods=['POST'])
def add_competitor():
    """Добавить конкурента"""
    try:
        user_id = get_user_id(request)
        if not user_id:
            return jsonify({"success": False, "error": "user_id не указан"}), 401
        
        data = request.json
        username = data.get('username', '').strip()
        
        if not username:
            return jsonify({"success": False, "error": "Username обязателен"}), 400
        
        monitor.add_competitor(user_id, username)
        
        return jsonify({
            "success": True,
            "message": f"Конкурент @{username} добавлен"
        })
    except Exception as e:
        logger.error(f"Ошибка в POST /api/competitors: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/api/competitors/<username>', methods=['DELETE'])
def remove_competitor(username):
    """Удалить конкурента"""
    try:
        user_id = get_user_id(request)
        if not user_id:
            return jsonify({"success": False, "error": "user_id не указан"}), 401
        
        if not username:
            return jsonify({"success": False, "error": "Username обязателен"}), 400
        
        monitor.remove_competitor(user_id, username)
        
        return jsonify({
            "success": True,
            "message": f"Конкурент @{username} удалён"
        })
    except Exception as e:
        logger.error(f"Ошибка в DELETE /api/competitors: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/api/alerts', methods=['GET'])
def get_alerts():
    """Получить алерты пользователя"""
    try:
        user_id = get_user_id(request)
        if not user_id:
            return jsonify({"success": False, "error": "user_id не указан"}), 401
        
        limit = request.args.get('limit', 10, type=int)
        alerts = api.get_alerts(user_id, limit=limit)
        
        return jsonify({"success": True, "data": alerts})
    except Exception as e:
        logger.error(f"Ошибка в /api/alerts: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/api/trigger-check', methods=['POST'])
def trigger_manual_check():
    """Запустить внеплановую проверку для пользователя"""
    try:
        user_id = get_user_id(request)
        if not user_id:
            return jsonify({"success": False, "error": "user_id не указан"}), 401
        
        async def check():
            await monitor.monitor_user(user_id)
        
        asyncio.run(check())
        
        return jsonify({"success": True, "message": "Проверка запущена"})
    except Exception as e:
        logger.error(f"Ошибка в /api/trigger-check: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/api/status', methods=['GET'])
def get_status():
    """Получить статус мониторинга пользователя"""
    try:
        user_id = get_user_id(request)
        if not user_id:
            return jsonify({"success": False, "error": "user_id не указан"}), 401
        
        competitors = monitor.get_competitors(user_id)
        
        return jsonify({
            "success": True,
            "data": {
                "active": True,
                "competitors_count": len(competitors),
                "config": {
                    "posts_limit": Config.POSTS_LIMIT,
                    "posts_max_age_hours": Config.POSTS_MAX_AGE_HOURS,
                    "monitoring_interval_minutes": Config.MONITORING_INTERVAL_MINUTES,
                    "trend_growth_threshold": Config.TREND_GROWTH_THRESHOLD,
                    "trend_max_post_age_hours": Config.TREND_MAX_POST_AGE_HOURS,
                }
            }
        })
    except Exception as e:
        logger.error(f"Ошибка в /api/status: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/health', methods=['GET'])
def health_check():
    """Проверка работоспособности сервера"""
    return jsonify({
        "status": "ok",
        "service": "instagram-monitor-api",
        "version": "2.0-multiuser"
    })


if __name__ == '__main__':
    logger.info("Запуск Flask API сервера...")
    app.run(host='0.0.0.0', port=5000, debug=False)
