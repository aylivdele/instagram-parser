# Миграция на мультипользовательскую систему

## Что изменилось

### 🔄 Мультипользовательская поддержка

**Было:**
- Глобальный список конкурентов для всех
- Уведомления во все чаты из TELEGRAM_CHAT_IDS

**Стало:**
- Каждый пользователь имеет свой список конкурентов
- Уведомления только создателю конкурента
- Полная изоляция данных между пользователями

### ⚙️ Конфигурируемые параметры

Теперь **все** пороги и настройки вынесены в переменные окружения:

```env
# Мониторинг
POSTS_LIMIT=10                      # постов за проверку
POSTS_MAX_AGE_HOURS=48              # максимальный возраст поста
MONITORING_INTERVAL_MINUTES=60      # интервал проверок

# Детекция трендов
TREND_GROWTH_THRESHOLD=150          # минимальный рост (%)
TREND_MAX_POST_AGE_HOURS=24         # макс. возраст для тренда
TREND_MIN_SNAPSHOTS=2               # мин. проверок
TREND_SPEED_MULTIPLIER=2.0          # множитель скорости
```

Можно менять без перекомпиляции — просто редактируйте `.env` и `docker compose restart api`.

---

## Схема базы данных

### Новые таблицы:

**`users`** — пользователи системы
```sql
CREATE TABLE users (
    user_id TEXT PRIMARY KEY,           -- "telegram_123456" или "browser_abc123"
    telegram_chat_id TEXT UNIQUE,       -- для отправки уведомлений
    created_at TIMESTAMP,
    last_active TIMESTAMP
)
```

**`competitors`** — теперь с `user_id`
```sql
CREATE TABLE competitors (
    id INTEGER PRIMARY KEY,
    user_id TEXT NOT NULL,              -- владелец конкурента
    username TEXT NOT NULL,
    added_at TIMESTAMP,
    avg_views_per_hour REAL,
    UNIQUE(user_id, username)           -- один конкурент = один владелец
)
```

**`post_snapshots`** — теперь с `user_id`
```sql
CREATE TABLE post_snapshots (
    id INTEGER PRIMARY KEY,
    user_id TEXT NOT NULL,              -- чьи данные
    post_id TEXT,
    username TEXT,
    ...
)
```

**`alerts`** — теперь с `user_id`
```sql
CREATE TABLE alerts (
    id INTEGER PRIMARY KEY,
    user_id TEXT NOT NULL,              -- кому алерт
    post_id TEXT,
    username TEXT,
    ...
)
```

---

## Миграция существующей базы данных

Если у вас уже есть данные в старой БД, выполните миграцию:

```bash
# 1. Сделайте бэкап
docker compose exec api sqlite3 /data/instagram_monitor.db ".backup /tmp/old_backup.db"
docker cp instagram_monitor_api:/tmp/old_backup.db ./backup_before_migration.db

# 2. Запустите миграцию
docker compose exec api python3 << 'PYEOF'
import sqlite3
from datetime import datetime

conn = sqlite3.connect('/data/instagram_monitor.db')
cursor = conn.cursor()

# Создаём DEFAULT_USER для старых данных
DEFAULT_USER = "migrated_user"

# Создаём таблицу users если её нет
cursor.execute("""
    CREATE TABLE IF NOT EXISTS users (
        user_id TEXT PRIMARY KEY,
        telegram_chat_id TEXT UNIQUE,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        last_active TIMESTAMP
    )
""")

# Регистрируем дефолтного пользователя
cursor.execute("""
    INSERT OR IGNORE INTO users (user_id, last_active)
    VALUES (?, ?)
""", (DEFAULT_USER, datetime.now()))

# Проверяем наличие user_id колонки
cursor.execute("PRAGMA table_info(competitors)")
columns = [row[1] for row in cursor.fetchall()]

if 'user_id' not in columns:
    print("Миграция competitors...")
    
    # Создаём новую таблицу
    cursor.execute("""
        CREATE TABLE competitors_new (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            username TEXT NOT NULL,
            added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            avg_views_per_hour REAL DEFAULT 0,
            total_posts_analyzed INTEGER DEFAULT 0,
            UNIQUE(user_id, username),
            FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
        )
    """)
    
    # Копируем данные
    cursor.execute(f"""
        INSERT INTO competitors_new (user_id, username, added_at, avg_views_per_hour, total_posts_analyzed)
        SELECT '{DEFAULT_USER}', username, added_at, avg_views_per_hour, total_posts_analyzed
        FROM competitors
    """)
    
    cursor.execute("DROP TABLE competitors")
    cursor.execute("ALTER TABLE competitors_new RENAME TO competitors")
    
    print("✓ competitors мигрирована")

# Аналогично для post_snapshots
cursor.execute("PRAGMA table_info(post_snapshots)")
columns = [row[1] for row in cursor.fetchall()]

if 'user_id' not in columns:
    print("Миграция post_snapshots...")
    
    cursor.execute("""
        CREATE TABLE post_snapshots_new (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            post_id TEXT NOT NULL,
            username TEXT NOT NULL,
            post_url TEXT,
            views INTEGER,
            likes INTEGER,
            checked_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            hours_since_posted REAL,
            FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
        )
    """)
    
    cursor.execute(f"""
        INSERT INTO post_snapshots_new (user_id, post_id, username, post_url, views, likes, checked_at, hours_since_posted)
        SELECT '{DEFAULT_USER}', post_id, username, post_url, views, likes, checked_at, hours_since_posted
        FROM post_snapshots
    """)
    
    cursor.execute("DROP TABLE post_snapshots")
    cursor.execute("ALTER TABLE post_snapshots_new RENAME TO post_snapshots")
    
    print("✓ post_snapshots мигрирована")

# Аналогично для alerts
cursor.execute("PRAGMA table_info(alerts)")
columns = [row[1] for row in cursor.fetchall()]

if 'user_id' not in columns:
    print("Миграция alerts...")
    
    cursor.execute("""
        CREATE TABLE alerts_new (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            post_id TEXT NOT NULL,
            username TEXT NOT NULL,
            post_url TEXT,
            views INTEGER,
            views_per_hour REAL,
            avg_views_per_hour REAL,
            growth_rate REAL,
            detected_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            sent_to_telegram BOOLEAN DEFAULT 0,
            FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
        )
    """)
    
    cursor.execute(f"""
        INSERT INTO alerts_new (user_id, post_id, username, post_url, views, views_per_hour, avg_views_per_hour, growth_rate, detected_at, sent_to_telegram)
        SELECT '{DEFAULT_USER}', post_id, username, post_url, views, views_per_hour, avg_views_per_hour, growth_rate, detected_at, sent_to_telegram
        FROM alerts
    """)
    
    cursor.execute("DROP TABLE alerts")
    cursor.execute("ALTER TABLE alerts_new RENAME TO alerts")
    
    print("✓ alerts мигрирована")

# Создаём индексы
cursor.execute("CREATE INDEX IF NOT EXISTS idx_competitors_user ON competitors(user_id)")
cursor.execute("CREATE INDEX IF NOT EXISTS idx_post_snapshots_user_username ON post_snapshots(user_id, username)")
cursor.execute("CREATE INDEX IF NOT EXISTS idx_post_snapshots_post_id ON post_snapshots(user_id, post_id, checked_at)")
cursor.execute("CREATE INDEX IF NOT EXISTS idx_alerts_user ON alerts(user_id, detected_at DESC)")

conn.commit()
conn.close()

print("\n✅ Миграция завершена успешно!")
print(f"Все старые данные привязаны к пользователю: {DEFAULT_USER}")
print("Теперь можно привязать telegram_chat_id через /api/register")
PYEOF

# 3. Привязываем telegram_chat_id к мигрированному пользователю
curl -X POST http://localhost/api/register \
  -H "Content-Type: application/json" \
  -d '{"user_id": "migrated_user", "telegram_chat_id": "YOUR_CHAT_ID"}'
```

---

## API Changes

### Все эндпоинты теперь требуют `user_id`

**Способы передачи:**

1. **Header (рекомендуется):**
```bash
curl http://localhost/api/competitors \
  -H "X-User-Id: telegram_123456"
```

2. **Query параметр:**
```bash
curl "http://localhost/api/competitors?user_id=telegram_123456"
```

3. **JSON body:**
```bash
curl http://localhost/api/competitors \
  -H "Content-Type: application/json" \
  -d '{"user_id": "telegram_123456"}'
```

### Новый эндпоинт `/api/register`

```bash
POST /api/register
{
  "user_id": "telegram_123456",
  "telegram_chat_id": "123456"  // опционально
}
```

Регистрирует пользователя и привязывает telegram_chat_id для уведомлений.

---

## Тестирование

### 1. Проверка конфигурации

```bash
docker compose up -d --build
docker compose logs api | head -20
```

Должно быть:
```
============================================================
Конфигурация Instagram Monitor:
  Постов за проверку: 10
  Макс. возраст поста: 48ч
  Интервал мониторинга: 60 мин
  ...
============================================================
```

### 2. Тестирование API

```bash
# Регистрация пользователя
curl -X POST http://localhost/api/register \
  -H "Content-Type: application/json" \
  -d '{"user_id": "test_user_1", "telegram_chat_id": "123456"}'

# Добавление конкурента
curl -X POST http://localhost/api/competitors \
  -H "Content-Type: application/json" \
  -H "X-User-Id: test_user_1" \
  -d '{"username": "nike"}'

# Проверка списка
curl http://localhost/api/competitors \
  -H "X-User-Id: test_user_1"
```

### 3. Проверка изоляции

```bash
# Пользователь 2 не должен видеть конкурентов пользователя 1
curl http://localhost/api/competitors \
  -H "X-User-Id: test_user_2"

# Должно вернуть: {"success": true, "data": []}
```

---

## Экспериментирование с параметрами

Хотите изменить чувствительность детекции? Редактируйте `.env`:

```env
# Более строгая детекция (меньше ложных срабатываний)
TREND_GROWTH_THRESHOLD=200
TREND_SPEED_MULTIPLIER=3.0
TREND_MIN_SNAPSHOTS=3

# Более мягкая детекция (больше алертов)
TREND_GROWTH_THRESHOLD=100
TREND_SPEED_MULTIPLIER=1.5
TREND_MIN_SNAPSHOTS=1
```

Затем:
```bash
docker compose restart api
```

Изменения применятся мгновенно, без пересборки.

---

## Troubleshooting

**Ошибка: "user_id не указан"**
- Убедитесь, что передаёте `X-User-Id` в заголовке
- Проверьте, что HTML правильно извлекает user_id из Telegram

**Не приходят уведомления:**
- Проверьте, что пользователь зарегистрирован: `SELECT * FROM users WHERE user_id = 'ваш_id'`
- Убедитесь, что `telegram_chat_id` задан
- Проверьте логи: `docker compose logs api | grep Telegram`

**Конкуренты не появляются:**
- Проверьте изоляцию: используете ли один и тот же `user_id` при добавлении и просмотре
- Проверьте логи: `docker compose logs api`
