# Инструкции по деплою Telegram бота на Render

## Переменные окружения в Render Dashboard

Установите следующие переменные окружения в Render Dashboard:

### Обязательные переменные:
- `TELEGRAM_BOT_TOKEN` - токен вашего Telegram бота (получить у @BotFather)
- `RENDER_APP_NAME` - имя вашего приложения на Render (например: `my-telegram-bot`)

### Источник расписания (выберите один из вариантов):

**Вариант 1: Получение с my.itmo.ru (рекомендуется)**
- `ITMO_LOGIN` - ваш логин ITMO ID
- `ITMO_PASSWORD` - ваш пароль ITMO ID

**Вариант 2: Статическое расписание из JSON**
- `SCHEDULE_JSON` - JSON с расписанием занятий

### Опциональные переменные:
- `PORT` - порт для веб-сервера (по умолчанию: 10000)
- `WEBHOOK_URL` - полный URL webhook (если не установлен RENDER_APP_NAME)

## Настройка Render Web Service

1. **Build Command**: `pip install -r requirements.txt`
2. **Start Command**: `python main.py`
3. **Python Version**: 3.11.9 (указано в runtime.txt)

## Автоматическая установка Webhook

Бот автоматически установит webhook при запуске на URL:
`https://<RENDER_APP_NAME>.onrender.com/webhook`

## Проверка работы

После деплоя проверьте:
- Главная страница: `https://<RENDER_APP_NAME>.onrender.com/` - должна показать "Bot is running"
- Статус: `https://<RENDER_APP_NAME>.onrender.com/status` - JSON с информацией о боте
- Health check: `https://<RENDER_APP_NAME>.onrender.com/health` - проверка работоспособности

## Логи

Все события логируются в консоль Render:
- Успешный запуск сервера
- Установка webhook
- Получение и обработка обновлений от Telegram

## Особенности Render Free Tier

- Приложение может "засыпать" после 15 минут неактивности
- При первом запросе после сна может потребоваться время на "пробуждение"
- Webhook автоматически переустанавливается при каждом запуске
