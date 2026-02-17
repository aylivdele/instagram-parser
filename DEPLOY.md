# 🚀 Деплой Instagram Monitor в Docker с HTTPS

## Архитектура

```
Интернет (443/80)
      │
  [Caddy]  ← автоматический Let's Encrypt сертификат
      │
      ├── /             → instagram-monitor.html (статика)
      ├── /api/*        → Flask API (порт 5000, внутри Docker)
      └── /health       → healthcheck
            │
         [Flask]
            │
         [SQLite]  ← /data/instagram_monitor.db (volume)
```

---

## Шаг 1 — Подготовка сервера

Нужен VPS с публичным IP и доменом, направленным на этот IP.

```bash
# Установка Docker (Ubuntu/Debian)
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker $USER
newgrp docker

# Проверка
docker --version
docker compose version
```

---

## Шаг 2 — Структура файлов

Создайте папку проекта и разместите файлы:

```
instagram-monitor/
├── docker-compose.yml
├── Dockerfile
├── Caddyfile
├── .env                        ← создать из .env.example
├── .env.example
├── api_server.py               ← обновлённая версия
├── instagram_monitor.py
├── instagram-monitor.html
└── requirements.txt            ← обновлённая версия
```

```bash
mkdir instagram-monitor && cd instagram-monitor
# Скопируйте все файлы в эту папку
```

---

## Шаг 3 — DNS и сертификат

### Let's Encrypt (рекомендуется — для VPS с доменом)

Caddy сам получит сертификат. Нужно только:

1. **Направить DNS-запись на IP сервера:**
   ```
   Тип: A
   Имя: monitor (или @ для корневого)
   Значение: 1.2.3.4  ← IP вашего VPS
   TTL: 300
   ```

2. **Убедиться, что порты 80 и 443 открыты:**
   ```bash
   sudo ufw allow 80
   sudo ufw allow 443
   # Или через iptables:
   sudo iptables -A INPUT -p tcp --dport 80 -j ACCEPT
   sudo iptables -A INPUT -p tcp --dport 443 -j ACCEPT
   ```

3. **Отредактировать Caddyfile** — заменить `YOUR_DOMAIN.COM`:
   ```
   # Было:
   YOUR_DOMAIN.COM {
   
   # Стало:
   monitor.example.com {
   ```

Caddy автоматически получит и будет обновлять сертификат при первом запуске.

---

### Self-signed (для тестов без домена)

Если домена нет, но нужен HTTPS (например, Telegram требует HTTPS для Mini App):

```bash
# Генерация самоподписного сертификата
mkdir -p certs
openssl req -x509 -newkey rsa:4096 -nodes \
  -keyout certs/key.pem \
  -out certs/cert.pem \
  -days 365 \
  -subj "/CN=localhost" \
  -addext "subjectAltName=IP:$(curl -s ifconfig.me)"

echo "Сертификат создан в ./certs/"
```

Затем замените `Caddyfile` на вариант с self-signed:

```
# Caddyfile для self-signed (замените IP на ваш)
:443 {
    tls /etc/caddy/certs/cert.pem /etc/caddy/certs/key.pem

    handle / {
        root * /srv
        try_files /instagram-monitor.html =404
        file_server
    }

    handle /api/* {
        reverse_proxy api:5000
    }

    handle /health {
        reverse_proxy api:5000
    }
}

:80 {
    redir https://{host}{uri} permanent
}
```

И добавьте volume в `docker-compose.yml` для сервиса `caddy`:
```yaml
volumes:
  - ./certs:/etc/caddy/certs:ro
```

---

## Шаг 4 — Настройка переменных окружения

```bash
cp .env.example .env
nano .env
```

Заполните:
```env
TELEGRAM_BOT_TOKEN=1234567890:AAxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
TELEGRAM_CHAT_ID=123456789
```

Как получить значения:
- **TELEGRAM_BOT_TOKEN** — создайте бота у @BotFather (`/newbot`)
- **TELEGRAM_CHAT_ID** — напишите что-нибудь боту @userinfobot

---

## Шаг 5 — Запуск

```bash
# Сборка и запуск (первый раз)
docker compose up -d --build

# Проверка статуса
docker compose ps

# Логи всех сервисов
docker compose logs -f

# Логи только API
docker compose logs -f api

# Логи только Caddy (включая получение сертификата)
docker compose logs -f caddy
```

После запуска Caddy в логах должно появиться:
```
... certificate obtained successfully
```

---

## Шаг 6 — Проверка

```bash
# Health check API
curl https://monitor.example.com/health

# Список конкурентов
curl https://monitor.example.com/api/competitors

# Добавить конкурента
curl -X POST https://monitor.example.com/api/competitors \
  -H "Content-Type: application/json" \
  -d '{"username": "nike"}'
```

Откройте в браузере: `https://monitor.example.com`

---

## Шаг 7 — Настройка Telegram Mini App

В файле `instagram-monitor.html` замените URL API:
```javascript
// Было:
const API_URL = 'http://localhost:5000/api';

// Стало:
const API_URL = 'https://monitor.example.com/api';
```

Затем в @BotFather:
1. `/newapp` → выберите бота
2. URL веб-приложения: `https://monitor.example.com`

---

## Управление

```bash
# Остановить
docker compose down

# Перезапустить после изменений в коде
docker compose up -d --build

# Посмотреть базу данных
docker compose exec api sqlite3 /data/instagram_monitor.db ".tables"
docker compose exec api sqlite3 /data/instagram_monitor.db "SELECT * FROM competitors;"

# Зайти внутрь контейнера API
docker compose exec api bash

# Обновить только один сервис
docker compose up -d --build api
```

---

## Обновление сертификата (Let's Encrypt)

Caddy обновляет сертификат **автоматически** за 30 дней до истечения.
Ничего дополнительно делать не нужно — сертификаты хранятся в volume `caddy_data`.

---

## Решение проблем

**Сертификат не выдаётся:**
- Проверьте, что домен указывает на IP сервера: `nslookup monitor.example.com`
- Проверьте, что порты 80 и 443 открыты: `nc -zv monitor.example.com 80`
- Посмотрите логи Caddy: `docker compose logs caddy`

**API не отвечает:**
- Проверьте healthcheck: `docker compose ps`
- Посмотрите логи: `docker compose logs api`

**Telegram Mini App не открывается:**
- Mini App требует валидный HTTPS-сертификат (не self-signed)
- Убедитесь, что домен доступен публично

**База данных не сохраняется после перезапуска:**
- Volume `db_data` должен существовать: `docker volume ls`
- Не используйте `docker compose down -v` — это удаляет volumes!
