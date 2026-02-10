import os
import json
import logging
import time
import pickle
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes

# Настройка логирования (должна быть до импортов, которые используют logger)
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# Импортируем веб-сервер
try:
    from web_server import initialize_telegram_app, run_server, update_bot_status
except ImportError:
    def initialize_telegram_app(app):
        pass

    def run_server():
        pass

    def update_bot_status(**kwargs):
        pass

# Глобальные переменные
SCHEDULE_DATA = None
USERS_FILE = "bot_users.pkl"

def load_users():
    """Загружает список пользователей из файла"""
    try:
        if os.path.exists(USERS_FILE):
            with open(USERS_FILE, 'rb') as f:
                return pickle.load(f)
        return set()
    except Exception as e:
        logger.error(f"Ошибка загрузки пользователей: {e}")
        return set()

def save_users(users):
    """Сохраняет список пользователей в файл"""
    try:
        with open(USERS_FILE, 'wb') as f:
            pickle.dump(users, f)
        logger.info(f"Сохранено {len(users)} пользователей")
    except Exception as e:
        logger.error(f"Ошибка сохранения пользователей: {e}")

def add_user(user_id):
    """Добавляет пользователя в список"""
    users = load_users()
    users.add(user_id)
    save_users(users)

def load_schedule():
    """Загружает статическое расписание из переменной окружения SCHEDULE_JSON.

    Ожидаемый формат (пример):
    {
      "9.02": [
        {
          "subject": "Технические средства охраны",
          "start": "09:50",
          "end": "11:20",
          "room": "311",
          "address": "Песочная наб., д.14, лит.А",
          "teacher": "Волхонский Владимир Владимирович"
        }
      ],
      "10.02": []
    }
    """
    global SCHEDULE_DATA

    schedule_json = os.getenv("SCHEDULE_JSON")
    if not schedule_json:
        logger.error("❌ Переменная окружения SCHEDULE_JSON не установлена")
        SCHEDULE_DATA = None
        return

    try:
        SCHEDULE_DATA = json.loads(schedule_json)
        if not isinstance(SCHEDULE_DATA, dict):
            raise ValueError("SCHEDULE_JSON должен быть объектом JSON (словарь с ключами-д датами)")

        logger.info("✅ Расписание загружено из переменной окружения SCHEDULE_JSON")
        logger.info(f"Всего дней в расписании: {len(SCHEDULE_DATA)}")
    except Exception as e:
        logger.error(f"❌ Ошибка парсинга JSON расписания: {e}")
        SCHEDULE_DATA = None

def get_current_week_type(target_date=None):
    """Определяет тип текущей недели (четная/нечетная)"""
    if target_date is None:
        # Используем московское время
        moscow_tz = ZoneInfo("Europe/Moscow")
        target_date = datetime.now(moscow_tz)

    # Находим ближайший понедельник в прошлом (день отсчета)
    days_since_monday = (target_date.weekday() - 0) % 7  # 0 = понедельник
    if days_since_monday == 0:  # Если сегодня понедельник
        reference_monday = target_date
    else:
        reference_monday = target_date - timedelta(days=days_since_monday)

    # Базовая дата - 6 октября 2025, понедельник, начало четной недели
    base_date = datetime(2025, 10, 6, tzinfo=ZoneInfo("Europe/Moscow"))  # понедельник

    # Вычисляем количество недель с базовой даты до дня отсчета
    days_since_base = (reference_monday - base_date).days
    weeks_since_base = days_since_base // 7

    # Определяем тип недели на основе дня отсчета
    # Базовая дата - начало четной недели, поэтому:
    # Если день отсчета - четное количество недель от базовой даты - четная неделя
    # Если день отсчета - нечетное количество недель от базовой даты - нечетная неделя
    if weeks_since_base % 2 == 0:
        return 2  # четная неделя
    else:
        return 1  # нечетная неделя

def get_weekday_name(date):
    """Получает название дня недели на русском"""
    weekdays = {
        0: "Понедельник",
        1: "Вторник",
        2: "Среда",
        3: "Четверг",
        4: "Пятница",
        5: "Суббота",
        6: "Воскресенье"
    }
    return weekdays[date.weekday()]


def _parse_time(time_str: str) -> datetime:
    """Парсит время HH:MM в объект datetime (без учета даты)."""
    return datetime.strptime(time_str, "%H:%M")


def _build_day_schedule(raw_classes):
    """Строит список занятий и окон на день из списков занятий по дате.

    raw_classes — список словарей:
      - subject: название предмета
      - start: время начала пары HH:MM
      - end: время окончания пары HH:MM
      - room / address / teacher: опционально
    """
    if not raw_classes:
        return []

    # Сортируем по времени начала
    try:
        sorted_raw = sorted(raw_classes, key=lambda item: _parse_time(item.get("start", "00:00")))
    except Exception as e:
        logger.error(f"❌ Ошибка сортировки занятий по времени: {e}")
        sorted_raw = raw_classes

    classes = []
    prev_end: datetime | None = None

    for raw in sorted_raw:
        subject = raw.get("subject", "Предмет не указан")
        start_str = raw.get("start")
        end_str = raw.get("end")

        if not start_str or not end_str:
            logger.warning(f"⚠️ Пропущено занятие без start/end: {subject}")
            continue

        try:
            start_dt = _parse_time(start_str)
            end_dt = _parse_time(end_str)
        except ValueError:
            logger.warning(f"⚠️ Неверный формат времени '{start_str}-{end_str}' для предмета '{subject}'")
            continue

        # Добавляем окно, если перерыв между парами больше 30 минут
        if prev_end is not None:
            gap_minutes = int((start_dt - prev_end).total_seconds() // 60)
            if gap_minutes > 30:
                window_item = {
                    "window": f"{prev_end.strftime('%H:%M')}-{start_dt.strftime('%H:%M')}",
                    "duration": f"{gap_minutes} мин",
                }
                classes.append(window_item)

        class_item = {
            "subject": subject,
            "time": f"{start_dt.strftime('%H:%M')}-{end_dt.strftime('%H:%M')}",
        }

        for key in ("room", "address", "teacher"):
            if key in raw:
                class_item[key] = raw[key]

        classes.append(class_item)
        prev_end = end_dt

    return classes


def format_class_info(class_item):
    """Форматирует информацию о занятии в минималистичном стиле"""
    if 'window' in class_item:
        return f"🪟 Окно {class_item['window']} ({class_item['duration']})"
    else:
        result = f"📚 {class_item.get('subject', 'Предмет не указан')}\n"
        result += f"⏰ {class_item.get('time', 'Время не указано')}"
        
        if 'room' in class_item and class_item['room'] != 'Аудитория не указана':
            result += f" • Ауд. {class_item['room']}"
        
        result += "\n"
        
        if 'address' in class_item and class_item['address'] != 'Адрес не указан':
            result += f"📍 {class_item['address']}\n"
        
        if 'teacher' in class_item:
            result += f"👤 {class_item['teacher']}\n"
        
        return result

def get_schedule_for_date(date_str=None):
    """Получает расписание для указанной даты из SCHEDULE_JSON (по дате)."""
    try:
        if date_str:
            # Парсим дату в формате ДД.ММ или ДД/ММ
            date_str = date_str.strip()
            if "/" in date_str:
                day, month = map(int, date_str.split("/"))
            elif "." in date_str:
                day, month = map(int, date_str.split("."))
            else:
                return "❌ Неверный формат даты. Используйте формат ДД.ММ или ДД/ММ"

            year = datetime.now(ZoneInfo("Europe/Moscow")).year
            target_date = datetime(year, month, day, tzinfo=ZoneInfo("Europe/Moscow"))
        else:
            # Используем московское время
            target_date = get_moscow_time()

        weekday_name = get_weekday_name(target_date)
        date_formatted = target_date.strftime("%d.%m.%Y")

        if not SCHEDULE_DATA:
            return "❌ Расписание не загружено. Проверьте переменную окружения SCHEDULE_JSON"

        # Ключ в JSON в формате Д.ММ (например, 9.02, 10.03)
        key = f"{target_date.day}.{target_date.month:02d}"
        raw_classes = SCHEDULE_DATA.get(key, [])
        classes = _build_day_schedule(raw_classes)

        # Если список пустой - это выходной
        if not classes:
            return f"📅 {weekday_name} ({date_formatted})\n\n🆓 Выходной"

        response = f"📅 {weekday_name} ({date_formatted})\n\n"
        for class_item in classes:
            response += format_class_info(class_item) + "\n"

        return response
    except ValueError:
        return "❌ Неверный формат даты. Используйте формат ДД.ММ или ДД/ММ"
    except Exception as e:
        logger.error(f"Ошибка получения расписания: {e}")
        return "❌ Ошибка при получении расписания"

def get_week_schedule():
    """Получает расписание на текущую неделю из SCHEDULE_JSON (по датам)."""
    current_time = get_moscow_time()
    days_since_monday = current_time.weekday()
    week_start = current_time - timedelta(days=days_since_monday)
    week_end = week_start + timedelta(days=6)
    if not SCHEDULE_DATA:
        return "❌ Расписание не загружено. Проверьте переменную окружения SCHEDULE_JSON"

    response = f"📅 Расписание на неделю ({week_start.strftime('%d.%m')} - {week_end.strftime('%d.%m.%Y')})\n\n"

    weekday_order = [
        "Понедельник",
        "Вторник",
        "Среда",
        "Четверг",
        "Пятница",
        "Суббота",
        "Воскресенье",
    ]

    for offset, day_name in enumerate(weekday_order):
        day_date = week_start + timedelta(days=offset)
        date_formatted = day_date.strftime("%d.%m")

        key = f"{day_date.day}.{day_date.month:02d}"
        raw_classes = SCHEDULE_DATA.get(key, [])
        classes = _build_day_schedule(raw_classes)

        response += f"📅 {day_name} ({date_formatted}):\n"

        # Если список пустой - это выходной
        if not classes:
            response += "   🆓 Выходной\n\n"
        else:
            for class_item in classes:
                class_text = format_class_info(class_item)
                indented = "\n".join(
                    f"   {line}" for line in class_text.split("\n") if line.strip()
                )
                response += f"{indented}\n"
            response += "\n"

    return response

def get_moscow_time():
    """Получает текущее время в Москве"""
    moscow_tz = ZoneInfo("Europe/Moscow")
    return datetime.now(moscow_tz)

def format_moscow_time(dt=None):
    """Форматирует время в московском часовом поясе"""
    if dt is None:
        dt = get_moscow_time()

    return dt.strftime("%d.%m.%Y %H:%M:%S (МСК)")

def is_new_day(current_time=None):
    """Проверяет, начался ли новый день по московскому времени"""
    if current_time is None:
        current_time = get_moscow_time()

    # Сравниваем с временем начала дня (00:00:00)
    day_start = current_time.replace(hour=0, minute=0, second=0, microsecond=0)

    # Если текущее время больше или равно началу дня, то день уже начался
    return current_time >= day_start

def get_days_since_date(target_date_str, current_time=None):
    """Вычисляет количество дней между датой и текущим временем в Москве"""
    if current_time is None:
        current_time = get_moscow_time()

    try:
        # Парсим целевую дату (предполагаем формат ДД.ММ.ГГГГ)
        target_date = datetime.strptime(target_date_str, "%d.%m.%Y")
        # Добавляем московский часовой пояс
        target_date = target_date.replace(tzinfo=ZoneInfo("Europe/Moscow"))

        # Вычисляем разницу в днях
        delta = current_time - target_date
        return delta.days

    except ValueError:
        return None

def get_main_menu():
    """Возвращает главное меню с командами"""
    keyboard = [
        [InlineKeyboardButton("📅 Сегодня", callback_data='today')],
        [InlineKeyboardButton("📆 Конкретная дата", callback_data='date')],
        [InlineKeyboardButton("📅 На неделю", callback_data='week')]
    ]
    return InlineKeyboardMarkup(keyboard)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /start"""
    user_id = update.message.from_user.id
    add_user(user_id)
    logger.info(f"Новый пользователь: {user_id}")

    await update.message.reply_text(
        '🎓 Добро пожаловать в бот расписания ИТМО!\n\n'
        'Выберите действие:',
        reply_markup=get_main_menu()
    )

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик нажатий кнопок"""
    query = update.callback_query
    await query.answer()

    if query.data == 'today':
        schedule = get_schedule_for_date()
        # Показываем расписание и меню
        await query.edit_message_text(
            text=f"{schedule}\n\nВыберите следующее действие:",
            reply_markup=get_main_menu()
        )

    elif query.data == 'date':
        await query.edit_message_text(
            text='📝 Введите дату в формате ДД.ММ или ДД/ММ (например: 25.12 или 25/12)\n\nПосле ввода даты выберите следующее действие:',
            reply_markup=get_main_menu()
        )
        context.user_data['waiting_for_date'] = True

    elif query.data == 'week':
        schedule = get_week_schedule()
        # Показываем расписание и меню
        await query.edit_message_text(
            text=f"{schedule}\n\nВыберите следующее действие:",
            reply_markup=get_main_menu()
        )

async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик текстовых сообщений"""
    if context.user_data.get('waiting_for_date'):
        date_str = update.message.text.strip()
        schedule = get_schedule_for_date(date_str)

        # Показываем расписание и меню
        await update.message.reply_text(
            f"{schedule}\n\nВыберите следующее действие:",
            reply_markup=get_main_menu()
        )
        context.user_data['waiting_for_date'] = False
    else:
        # Показываем меню для неизвестных команд
        await update.message.reply_text(
            '❓ Неизвестная команда. Выберите действие из меню:',
            reply_markup=get_main_menu()
        )

async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик ошибок"""
    logger.error(f'❌ Update {update} caused error {context.error}')
    import traceback
    logger.error(traceback.format_exc())
    if update and update.message:
        try:
            await update.message.reply_text('❌ Произошла ошибка. Попробуйте еще раз.')
        except Exception as e:
            logger.error(f"❌ Не удалось отправить сообщение об ошибке: {e}")

async def create_application():
    """Создает и настраивает Telegram Application асинхронно"""
    logger.info("🚀 Инициализация Telegram бота ИТМО...")

    # Инициализируем статическое расписание
    load_schedule()

    # Проверяем, что источник расписания доступен
    global SCHEDULE_DATA
    if not SCHEDULE_DATA:
        logger.error("❌ Не удалось инициализировать расписание из SCHEDULE_JSON")
        logger.error("Убедитесь, что переменная окружения SCHEDULE_JSON содержит корректный JSON.")
        return None

    # Проверяем токен
    token = os.getenv('TELEGRAM_BOT_TOKEN')
    if not token:
        logger.error("❌ Не найден токен бота в переменной окружения TELEGRAM_BOT_TOKEN")
        logger.error("Убедитесь, что переменная окружения TELEGRAM_BOT_TOKEN установлена в Render Dashboard")
        return None

    # Создаем приложение
    application = Application.builder().token(token).build()
    logger.info("📱 Application создан с токеном")

    # Инициализируем приложение асинхронно (обязательно для версии 21.7+)
    await application.initialize()
    logger.info("🔧 Application инициализирован асинхронно")

    # Регистрируем обработчики
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CallbackQueryHandler(button_handler))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))
    application.add_error_handler(error_handler)
    logger.info("🎯 Обработчики команд зарегистрированы")

    logger.info("✅ Telegram Application создан и настроен")
    return application

async def main():
    """Основная асинхронная функция запуска бота с webhook"""
    logger.info("🚀 Запуск Telegram бота ИТМО с webhook...")

    # Создаем Telegram Application асинхронно
    application = await create_application()
    if not application:
        logger.error("❌ Не удалось создать Telegram Application")
        return

    # Инициализируем веб-сервер с Telegram Application
    initialize_telegram_app(application)

    # Обновляем статус бота
    update_bot_status(running=True)

    logger.info("✅ Бот готов к работе через webhook")

    # Запускаем веб-сервер (блокирующий вызов)
    run_server()

if __name__ == '__main__':
    """Основная функция - точка входа"""
    try:
        import asyncio
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("⏹️ Остановка бота пользователем...")
        print("Бот остановлен пользователем")
    except Exception as e:
        logger.error(f"❌ Критическая ошибка бота: {e}")
        print(f"Критическая ошибка: {e}")
    finally:
        logger.info("⏹️ Работа завершена")
        print("Работа завершена")