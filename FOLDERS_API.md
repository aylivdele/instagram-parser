# API для работы с папками

## Эндпоинты

### GET `/api/folders`
Получить все папки пользователя

**Headers:**
```
X-User-Id: telegram_123456
```

**Response:**
```json
{
  "success": true,
  "data": [
    {
      "id": 1,
      "name": "Спорт",
      "color": "#0088cc",
      "icon": "⚽",
      "sort_order": 0,
      "count": 3
    }
  ]
}
```

---

### POST `/api/folders`
Создать новую папку

**Headers:**
```
X-User-Id: telegram_123456
Content-Type: application/json
```

**Body:**
```json
{
  "name": "Спорт",
  "color": "#0088cc",
  "icon": "⚽"
}
```

**Response:**
```json
{
  "success": true,
  "data": {
    "id": 1,
    "name": "Спорт",
    "color": "#0088cc",
    "icon": "⚽"
  }
}
```

---

### PATCH `/api/folders/<folder_id>`
Обновить папку

**Body** (все поля опциональны):
```json
{
  "name": "Спорт и фитнес",
  "color": "#ff0000",
  "icon": "🏃"
}
```

---

### DELETE `/api/folders/<folder_id>`
Удалить папку

Конкуренты из этой папки переместятся в "Без папки" (folder_id = NULL).

---

### POST `/api/folders/reorder`
Изменить порядок папок

**Body:**
```json
{
  "folder_ids": [3, 1, 2]
}
```

Папки будут отображаться в указанном порядке.

---

### POST `/api/competitors/<username>/move`
Переместить конкурента в папку

**Body:**
```json
{
  "folder_id": 1
}
```

Или убрать из папки:
```json
{
  "folder_id": null
}
```

---

### POST `/api/competitors`
Добавить конкурента (теперь с поддержкой folder_id)

**Body:**
```json
{
  "username": "nike",
  "folder_id": 1
}
```

---

## Примеры использования

### Создание папок и добавление конкурентов

```bash
# 1. Создать папку "Спорт"
curl -X POST http://localhost/api/folders \
  -H "Content-Type: application/json" \
  -H "X-User-Id: test_user" \
  -d '{"name": "Спорт", "icon": "⚽", "color": "#00aa00"}'

# Ответ: {"success": true, "data": {"id": 1, ...}}

# 2. Добавить конкурента в папку
curl -X POST http://localhost/api/competitors \
  -H "Content-Type: application/json" \
  -H "X-User-Id: test_user" \
  -d '{"username": "nike", "folder_id": 1}'

# 3. Добавить конкурента без папки
curl -X POST http://localhost/api/competitors \
  -H "Content-Type: application/json" \
  -H "X-User-Id: test_user" \
  -d '{"username": "adidas"}'

# 4. Переместить конкурента в другую папку
curl -X POST http://localhost/api/competitors/adidas/move \
  -H "Content-Type: application/json" \
  -H "X-User-Id: test_user" \
  -d '{"folder_id": 1}'

# 5. Убрать конкурента из папки
curl -X POST http://localhost/api/competitors/nike/move \
  -H "Content-Type: application/json" \
  -H "X-User-Id: test_user" \
  -d '{"folder_id": null}'
```

---

## Структура БД

### Таблица `folders`

```sql
CREATE TABLE folders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL,
    name TEXT NOT NULL,
    color TEXT DEFAULT '#0088cc',
    icon TEXT DEFAULT '📁',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    sort_order INTEGER DEFAULT 0,
    UNIQUE(user_id, name),
    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
);
```

### Обновлённая таблица `competitors`

```sql
CREATE TABLE competitors (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL,
    username TEXT NOT NULL,
    folder_id INTEGER,  -- ← НОВОЕ ПОЛЕ
    added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    avg_views_per_hour REAL DEFAULT 0,
    total_posts_analyzed INTEGER DEFAULT 0,
    UNIQUE(user_id, username),
    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE,
    FOREIGN KEY (folder_id) REFERENCES folders(id) ON DELETE SET NULL
);
```

**ON DELETE SET NULL** — при удалении папки конкуренты остаются, но переходят в "Без папки".

---

## Иконки (примеры)

```
📁 Общие
⚽ Спорт
🍔 Еда
👗 Мода
🎮 Игры
🎬 Кино
🎵 Музыка
📱 Технологии
✈️ Путешествия
💼 Бизнес
🏠 Дом
🐾 Животные
```

---

## Цвета (примеры)

```
#0088cc - синий (по умолчанию)
#ff3b30 - красный
#ff9500 - оранжевый
#ffcc00 - жёлтый
#34c759 - зелёный
#5856d6 - фиолетовый
#af52de - пурпурный
#ff2d55 - розовый
```

---

## Миграция существующих данных

Если у вас уже есть конкуренты без папок — ничего делать не нужно. У них `folder_id = NULL`, что означает "Без папки".

При создании новой папки она появится в интерфейсе, и конкурентов можно перетащить (или переместить через API).

---

## Frontend интеграция

В HTML уже реализованы:

1. **Список папок** с иконками, названиями и счётчиками
2. **Фильтрация конкурентов** по выбранной папке
3. **Кнопка создания** новой папки
4. **Удаление папок** с подтверждением
5. **Badge папки** на карточке конкурента (когда показаны все)

Клик по папке → показывает только конкурентов из этой папки.
Повторный клик → снова показывает всех.
