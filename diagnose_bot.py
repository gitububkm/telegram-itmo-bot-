#!/usr/bin/env python3
"""
Диагностика Telegram бота для Render
Запускайте локально для проверки всех систем
"""

import os
import sys
import json
import requests
import asyncio
from urllib.parse import urlparse

def check_environment_variables():
    """Проверяет переменные окружения"""
    print("🔍 ПРОВЕРКА ПЕРЕМЕННЫХ ОКРУЖЕНИЯ")
    print("=" * 50)

    required_vars = {
        'TELEGRAM_BOT_TOKEN': 'Токен Telegram бота',
        'SCHEDULE_JSON': 'JSON с расписанием',
        'RENDER_APP_NAME': 'Имя приложения Render (Bardyshev_schedulebot)'
    }

    optional_vars = {
        'PORT': 'Порт сервера (по умолчанию 10000)',
        'WEBHOOK_URL': 'Полный URL webhook (если не используется RENDER_APP_NAME)'
    }

    all_good = True

    for var, description in required_vars.items():
        value = os.getenv(var)
        if value:
            # Проверяем длину токена (должен быть примерно 46 символов)
            if var == 'TELEGRAM_BOT_TOKEN' and len(value) < 40:
                print(f"⚠️ {description}: значение подозрительно короткое ({len(value)} символов)")
            else:
                print(f"✅ {description}: УСТАНОВЛЕН")
        else:
            print(f"❌ {description}: НЕ УСТАНОВЛЕН")
            all_good = False

    print("\nОпциональные переменные:")
    for var, description in optional_vars.items():
        value = os.getenv(var)
        if value:
            print(f"✅ {description}: {value}")
        else:
            print(f"⚠️ {description}: не установлен (используется значение по умолчанию)")

    return all_good

def check_render_service():
    """Проверяет доступность сервиса на Render"""
    print("\n🌐 ПРОВЕРКА СЕРВИСА RENDER")
    print("=" * 50)

    app_name = os.getenv('RENDER_APP_NAME', 'Bardyshev_schedulebot')
    base_url = f"https://{app_name}.onrender.com"

    endpoints = [
        ('Главная страница', '/', 'Bot is running'),
        ('Статус', '/status', 'bot_running'),
        ('Здоровье', '/health', 'status'),
        ('Проверка webhook', '/check-webhook', 'webhook_url')
    ]

    all_good = True

    for name, endpoint, check_key in endpoints:
        try:
            response = requests.get(f"{base_url}{endpoint}", timeout=10)
            if response.status_code == 200:
                print(f"✅ {name}: Доступна")

                if check_key:
                    try:
                        data = response.json()
                        if check_key in data:
                            print(f"   📊 {check_key}: {data[check_key]}")
                        else:
                            print(f"   ⚠️ Ключ {check_key} не найден в ответе")
                    except:
                        print(f"   📝 Ответ: {response.text[:100]}...")
            else:
                print(f"❌ {name}: Ошибка {response.status_code}")
                all_good = False

        except requests.exceptions.RequestException as e:
            print(f"❌ {name}: Не доступна - {e}")
            all_good = False

    return all_good

def check_telegram_webhook():
    """Проверяет настройки webhook в Telegram"""
    print("\n📡 ПРОВЕРКА WEBHOOK В TELEGRAM")
    print("=" * 50)

    token = os.getenv('TELEGRAM_BOT_TOKEN')
    app_name = os.getenv('RENDER_APP_NAME', 'Bardyshev_schedulebot')

    if not token:
        print("❌ TELEGRAM_BOT_TOKEN не установлен")
        return False

    expected_webhook_url = f"https://{app_name}.onrender.com/webhook"

    try:
        response = requests.get(f"https://api.telegram.org/bot{token}/getWebhookInfo", timeout=10)
        if response.status_code == 200:
            data = response.json()
            if data.get('ok'):
                webhook_info = data.get('result', {})

                print(f"📍 Текущий webhook URL: {webhook_info.get('url', 'не установлен')}")
                print(f"🎯 Ожидаемый URL: {expected_webhook_url}")
                print(f"📊 Ожидающих обновлений: {webhook_info.get('pending_update_count', 0)}")

                if webhook_info.get('url') == expected_webhook_url:
                    print("✅ Webhook настроен правильно!")
                    return True
                else:
                    print("❌ Webhook настроен неправильно")
                    print(f"   Требуется: {expected_webhook_url}")
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

def check_bot_info():
    """Получает информацию о боте"""
    print("\n🤖 ИНФОРМАЦИЯ О БОТЕ")
    print("=" * 50)

    token = os.getenv('TELEGRAM_BOT_TOKEN')

    if not token:
        print("❌ TELEGRAM_BOT_TOKEN не установлен")
        return False

    try:
        response = requests.get(f"https://api.telegram.org/bot{token}/getMe", timeout=10)
        if response.status_code == 200:
            data = response.json()
            if data.get('ok'):
                bot_info = data.get('result', {})
                print(f"📛 Имя бота: {bot_info.get('first_name')}")
                print(f"👤 Username: @{bot_info.get('username')}")
                print(f"🆔 ID: {bot_info.get('id')}")
                print(f"🌐 Может присоединяться к группам: {bot_info.get('can_join_groups', False)}")
                print(f"🤖 Это бот: {bot_info.get('is_bot', False)}")

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

def test_schedule_json():
    """Проверяет валидность JSON расписания"""
    print("\n📅 ПРОВЕРКА РАСПИСАНИЯ")
    print("=" * 50)

    schedule_json = os.getenv('SCHEDULE_JSON')

    if not schedule_json:
        print("❌ SCHEDULE_JSON не установлен")
        return False

    try:
        data = json.loads(schedule_json)
        print("✅ JSON валиден")

        if 'schedule' in data:
            schedule = data['schedule']
            print(f"✅ Найден раздел 'schedule' с {len(schedule)} неделями")

            for i, week in enumerate(schedule):
                if 'week' in week and 'days' in week:
                    print(f"   📅 Неделя {week['week']}: {len(week['days'])} дней")
                else:
                    print(f"   ⚠️ Неделя {i+1}: неправильная структура")
        else:
            print("❌ Раздел 'schedule' не найден в JSON")
            return False

        return True

    except json.JSONDecodeError as e:
        print(f"❌ Невалидный JSON: {e}")
        return False
    except Exception as e:
        print(f"❌ Ошибка при обработке JSON: {e}")
        return False

def run_full_diagnosis():
    """Запускает полную диагностику"""
    print("🔍 ПОЛНАЯ ДИАГНОСТИКА TELEGRAM БОТА")
    print("=" * 60)
    print(f"📅 Время диагностики: {__import__('datetime').datetime.now()}")
    print("=" * 60)

    tests = [
        ("Переменные окружения", check_environment_variables),
        ("Информация о боте", check_bot_info),
        ("JSON расписания", test_schedule_json),
        ("Статус Render", check_render_service),
        ("Webhook Telegram", check_telegram_webhook),
    ]

    results = []

    for test_name, test_func in tests:
        print(f"\n{'='*20} {test_name} {'='*20}")
        try:
            result = test_func()
            results.append((test_name, result))
        except Exception as e:
            print(f"💥 Критическая ошибка в тесте {test_name}: {e}")
            results.append((test_name, False))

    # Итоги
    print(f"\n{'='*60}")
    print("📊 РЕЗУЛЬТАТЫ ДИАГНОСТИКИ")
    print(f"{'='*60}")

    passed = 0
    total = len(results)

    for test_name, success in results:
        status = "✅ ПРОЙДЕН" if success else "❌ ПРОВАЛЕН"
        print(f"{test_name}: {status}")

        if success:
            passed += 1

    print(f"\n🎯 ИТОГОВЫЙ РЕЗУЛЬТАТ: {passed}/{total} тестов пройдено")

    if passed == total:
        print("🎉 ВСЕ ТЕСТЫ ПРОЙДЕНЫ! Бот должен работать корректно.")
        print("\n📝 Если бот все еще не отвечает в Telegram:")
        print("   1. Попробуйте отправить команду /start боту")
        print("   2. Проверьте логи на Render в Dashboard")
        print("   3. Убедитесь, что бот не заблокирован в Telegram")
    elif passed >= total // 2:
        print("⚠️ Некоторые проблемы обнаружены, но бот может работать")
        print("   Рекомендуется исправить проваленные тесты")
    else:
        print("❌ Критические проблемы обнаружены!")
        print("   Необходимо исправить проваленные тесты перед запуском")

    return passed == total

if __name__ == "__main__":
    try:
        success = run_full_diagnosis()

        if not success:
            print(f"\n💡 Для диагностики с вашими реальными переменными окружения:")
            print(f"   1. Скопируйте этот файл на сервер с вашими переменными")
            print(f"   2. Или запустите диагностику онлайн:")
            print(f"      curl -s https://Bardyshev_schedulebot.onrender.com/check-webhook")

        sys.exit(0 if success else 1)

    except KeyboardInterrupt:
        print("\n\n👋 Диагностика прервана пользователем")
        sys.exit(1)
    except Exception as e:
        print(f"\n💥 Критическая ошибка: {e}")
        sys.exit(1)
