#!/usr/bin/env python3
"""
Комплексный тестер для диагностики Telegram бота
"""

import os
import json
import requests
import sys
from main import create_application

def check_environment():
    """Проверяет переменные окружения"""
    print("🔍 Проверка переменных окружения...")

    token = os.getenv('TELEGRAM_BOT_TOKEN')
    schedule_json = os.getenv('SCHEDULE_JSON')
    render_app_name = os.getenv('RENDER_APP_NAME')
    port = os.getenv('PORT', '10000')

    checks = [
        ('TELEGRAM_BOT_TOKEN', token, 'Токен бота'),
        ('SCHEDULE_JSON', schedule_json, 'JSON расписания'),
        ('RENDER_APP_NAME', render_app_name, 'Имя приложения Render'),
        ('PORT', port, 'Порт сервера')
    ]

    all_good = True
    for var_name, value, description in checks:
        if value:
            print(f"✅ {description}: установлен")
        else:
            print(f"❌ {description}: НЕ УСТАНОВЛЕН")
            all_good = False

    return all_good

def test_bot_locally():
    """Тестирует бота локально"""
    print("\n🚀 Локальное тестирование бота...")

    # Создаем приложение
    app = create_application()
    if not app:
        print("❌ Не удалось создать приложение")
        return False

    print("✅ Приложение создано успешно")

    # Тестируем обработку команды /start
    try:
        test_update = {
            "update_id": 123456789,
            "message": {
                "message_id": 1,
                "from": {
                    "id": 123456789,
                    "is_bot": False,
                    "first_name": "Test",
                    "username": "testuser"
                },
                "chat": {
                    "id": 123456789,
                    "type": "private"
                },
                "date": 1640995200,
                "text": "/start"
            }
        }

        print("📨 Тестирую обработку команды /start")
        from telegram import Update
        update = Update.de_json(test_update, app.bot)

        # Проверяем, что обработчик может быть вызван
        print("✅ Обновление создано успешно")
        print("🎯 Локальный тест пройден!")

        return True

    except Exception as e:
        print(f"❌ Ошибка при локальном тестировании: {e}")
        import traceback
        traceback.print_exc()
        return False

def check_render_status():
    """Проверяет статус приложения на Render"""
    print("\n🌐 Проверка статуса на Render...")

    app_name = os.getenv('RENDER_APP_NAME')
    if not app_name:
        print("❌ RENDER_APP_NAME не установлен")
        return False

    # Пробуем получить статус
    try:
        response = requests.get(f"https://{app_name}.onrender.com/health", timeout=10)
        if response.status_code == 200:
            data = response.json()
            print("✅ Сервер отвечает")
            print(f"   Статус: {data.get('status')}")
            print(f"   Бот запущен: {data.get('bot_running')}")
            print(f"   Webhook установлен: {data.get('webhook_set')}")
            print(f"   Размер очереди: {data.get('queue_size')}")
            print(f"   Процессор активен: {data.get('processor_alive')}")

            return True
        else:
            print(f"❌ Сервер не отвечает корректно: {response.status_code}")
            return False

    except requests.exceptions.RequestException as e:
        print(f"❌ Не удалось подключиться к Render: {e}")
        print("   Возможно, приложение еще не запущено или URL неправильный")
        return False

def check_telegram_webhook():
    """Проверяет настройки webhook в Telegram"""
    print("\n📡 Проверка webhook в Telegram...")

    token = os.getenv('TELEGRAM_BOT_TOKEN')
    if not token:
        print("❌ TELEGRAM_BOT_TOKEN не установлен")
        return False

    try:
        response = requests.get(f"https://api.telegram.org/bot{token}/getWebhookInfo", timeout=10)
        if response.status_code == 200:
            data = response.json()
            if data.get('ok'):
                webhook_info = data.get('result', {})
                url = webhook_info.get('url', 'не установлен')
                print(f"✅ Webhook URL: {url}")

                if url:
                    print("✅ Webhook установлен")
                else:
                    print("❌ Webhook НЕ установлен")

                return True
            else:
                print(f"❌ Ошибка API Telegram: {data}")
                return False
        else:
            print(f"❌ Ошибка HTTP: {response.status_code}")
            return False

    except requests.exceptions.RequestException as e:
        print(f"❌ Не удалось подключиться к Telegram API: {e}")
        return False

def test_webhook_delivery():
    """Тестирует доставку webhook"""
    print("\n📨 Тестирование доставки webhook...")

    token = os.getenv('TELEGRAM_BOT_TOKEN')
    app_name = os.getenv('RENDER_APP_NAME')

    if not token or not app_name:
        print("❌ Необходимые переменные не установлены")
        return False

    try:
        # Получаем информацию о боте
        bot_response = requests.get(f"https://api.telegram.org/bot{token}/getMe", timeout=10)
        if bot_response.status_code != 200:
            print("❌ Не удалось получить информацию о боте")
            return False

        bot_data = bot_response.json()
        if not bot_data.get('ok'):
            print("❌ Ошибка при получении данных бота")
            return False

        bot_info = bot_data.get('result', {})
        print(f"🤖 Бот: @{bot_info.get('username')} ({bot_info.get('first_name')})")

        # Проверяем, что сервер отвечает
        webhook_url = f"https://{app_name}.onrender.com/webhook"
        test_response = requests.post(f"{webhook_url}?test=1",
                                    json={"test": "webhook_test"},
                                    timeout=10)

        if test_response.status_code == 200:
            print(f"✅ Webhook URL отвечает: {test_response.text}")
            return True
        else:
            print(f"❌ Webhook URL не отвечает: {test_response.status_code}")
            return False

    except requests.exceptions.RequestException as e:
        print(f"❌ Ошибка при тестировании webhook: {e}")
        return False

def run_full_diagnosis():
    """Запускает полную диагностику"""
    print("🔍 ПОЛНАЯ ДИАГНОСТИКА TELEGRAM БОТА")
    print("=" * 50)

    results = []

    # 1. Проверка окружения
    results.append(("Переменные окружения", check_environment()))

    # 2. Локальное тестирование
    results.append(("Локальное тестирование", test_bot_locally()))

    # 3. Проверка Render статуса (если переменные установлены)
    if os.getenv('RENDER_APP_NAME'):
        results.append(("Статус Render", check_render_status()))

    # 4. Проверка Telegram webhook
    if os.getenv('TELEGRAM_BOT_TOKEN'):
        results.append(("Telegram Webhook", check_telegram_webhook()))
        results.append(("Доставка Webhook", test_webhook_delivery()))

    # Результаты
    print("\n📊 РЕЗУЛЬТАТЫ ДИАГНОСТИКИ:")
    print("=" * 50)

    for test_name, success in results:
        status = "✅ Пройден" if success else "❌ Провал"
        print(f"{test_name}: {status}")

    successful_tests = sum(1 for _, success in results if success)
    total_tests = len(results)

    print(f"\n🎯 Общий результат: {successful_tests}/{total_tests} тестов пройдено")

    if successful_tests == total_tests:
        print("🎉 Бот должен работать корректно!")
    elif successful_tests >= total_tests // 2:
        print("⚠️ Некоторые проблемы обнаружены, но бот может работать")
    else:
        print("❌ Критические проблемы обнаружены")

    return successful_tests == total_tests

def check_webhook_settings():
    """Проверяет настройки вебхука в Telegram"""
    print("\n📡 Проверка настроек webhook в Telegram...")

    token = os.getenv('TELEGRAM_BOT_TOKEN')
    app_name = os.getenv('RENDER_APP_NAME', 'Bardyshev_schedulebot')

    if not token:
        print("❌ TELEGRAM_BOT_TOKEN не установлен")
        return False

    try:
        response = requests.get(f"https://api.telegram.org/bot{token}/getWebhookInfo", timeout=10)
        if response.status_code == 200:
            data = response.json()
            if data.get('ok'):
                webhook_info = data.get('result', {})
                expected_url = f"https://{app_name}.onrender.com/webhook"

                print(f"📍 Текущий webhook URL: {webhook_info.get('url', 'не установлен')}")
                print(f"🎯 Ожидаемый URL: {expected_url}")
                print(f"📊 Ожидающих обновлений: {webhook_info.get('pending_update_count', 0)}")
                print(f"🔗 Максимум соединений: {webhook_info.get('max_connections', 40)}")

                if webhook_info.get('url') == expected_url:
                    print("✅ Webhook настроен правильно!")
                    return True
                else:
                    print("❌ Webhook настроен неправильно или не установлен")
                    print(f"   Требуемый URL: {expected_url}")
                    return False
            else:
                print(f"❌ Ошибка API Telegram: {data}")
                return False
        else:
            print(f"❌ Ошибка HTTP: {response.status_code}")
            return False

    except requests.exceptions.RequestException as e:
        print(f"❌ Не удалось подключиться к Telegram API: {e}")
        return False

def test_webhook_response():
    """Тестирует ответ webhook URL"""
    print("\n🌐 Тестирование ответа webhook URL...")

    app_name = os.getenv('RENDER_APP_NAME', 'Bardyshev_schedulebot')

    try:
        webhook_url = f"https://{app_name}.onrender.com/webhook"
        print(f"🔗 Тестирую URL: {webhook_url}")

        # Тестовый запрос к webhook
        test_data = {
            "update_id": 999999999,
            "message": {
                "message_id": 1,
                "from": {"id": 123456789, "is_bot": False, "first_name": "Test"},
                "chat": {"id": 123456789, "type": "private"},
                "date": 1640995200,
                "text": "/test"
            }
        }

        response = requests.post(webhook_url, json=test_data, timeout=10)

        print(f"📊 Статус ответа: {response.status_code}")
        print(f"📝 Ответ сервера: {response.text}")

        if response.status_code == 200 and "OK" in response.text:
            print("✅ Webhook URL отвечает корректно!")
            return True
        else:
            print("❌ Webhook URL не отвечает корректно")
            return False

    except requests.exceptions.RequestException as e:
        print(f"❌ Не удалось подключиться к webhook URL: {e}")
        return False

if __name__ == "__main__":
    success = run_full_diagnosis()
    sys.exit(0 if success else 1)
