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
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Импортируем модуль для работы с my.itmo.ru
try:
    from itmo_schedule import ITMOScheduleFetcher
except ImportError:
    ITMOScheduleFetcher = None
    logger.warning("Модуль itmo_schedule не найден, будет использоваться старая логика")

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
schedule_fetcher = None  # Объект для получения расписания с my.itmo.ru

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

async def notify_all_users(bot, message):
    """Отправляет уведомление всем пользователям"""
    users = load_users()
    success_count = 0
    error_count = 0

    for user_id in users:
        try:
            await bot.send_message(chat_id=user_id, text=message)
            success_count += 1
        except Exception as e:
            logger.warning(f"Не удалось отправить сообщение пользователю {user_id}: {e}")
            error_count += 1

    logger.info(f"Уведомления отправлены: {success_count} успешно, {error_count} ошибок")
    return success_count, error_count

def load_schedule():
    """Инициализирует загрузчик расписания с my.itmo.ru"""
    global schedule_fetcher
    
    # Проверяем, есть ли учетные данные для my.itmo.ru
    itmo_login = os.getenv('ITMO_LOGIN')
    itmo_password = os.getenv('ITMO_PASSWORD')
    
    if itmo_login and itmo_password and ITMOScheduleFetcher:
        try:
            schedule_fetcher = ITMOScheduleFetcher(itmo_login, itmo_password)
            logger.info("✅ Инициализирован загрузчик расписания с my.itmo.ru")
            
            # Пробуем авторизоваться сразу
            if schedule_fetcher.authenticate():
                logger.info("✅ Авторизация на my.itmo.ru успешна")
            else:
                logger.warning("⚠️ Не удалось авторизоваться на my.itmo.ru, будет попытка при первом запросе")
        except Exception as e:
            logger.error(f"❌ Ошибка инициализации загрузчика расписания: {e}")
            schedule_fetcher = None
    
    # Если нет учетных данных для my.itmo.ru, используем старый метод
    if not schedule_fetcher:
        global SCHEDULE_DATA
        schedule_json = os.getenv('SCHEDULE_JSON')
        if schedule_json:
            try:
                SCHEDULE_DATA = json.loads(schedule_json)
                logger.info("Расписание загружено из переменной окружения SCHEDULE_JSON")
            except json.JSONDecodeError as e:
                logger.error(f"Ошибка парсинга JSON расписания: {e}")
                SCHEDULE_DATA = None
        else:
            logger.warning("⚠️ Не найдены переменные ITMO_LOGIN/ITMO_PASSWORD или SCHEDULE_JSON")
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
    """Получает расписание для указанной даты"""
    global schedule_fetcher
    
    try:
        if date_str:
            # Парсим дату в формате ДД.ММ
            day, month = map(int, date_str.split('.'))
            year = datetime.now(ZoneInfo("Europe/Moscow")).year
            target_date = datetime(year, month, day, tzinfo=ZoneInfo("Europe/Moscow"))
        else:
            # Используем московское время
            target_date = get_moscow_time()

        weekday_name = get_weekday_name(target_date)
        date_formatted = target_date.strftime('%d.%m.%Y')

        # Если есть загрузчик с my.itmo.ru, используем его
        if schedule_fetcher:
            try:
                schedule_data = schedule_fetcher.get_schedule_for_date(target_date)
                
                if schedule_data and schedule_data.get('classes'):
                    response = f"📅 {weekday_name} ({date_formatted})\n\n"
                    
                    for class_item in schedule_data['classes']:
                        response += format_class_info(class_item) + "\n"
                    
                    return response
                else:
                    return f"📅 {weekday_name} ({date_formatted})\n\n🆓 Нет занятий"
            except Exception as e:
                logger.error(f"Ошибка получения расписания с my.itmo.ru: {e}")
                # Пробуем использовать старый метод как fallback
                pass

        # Используем старый метод (из переменной окружения)
        if not SCHEDULE_DATA:
            return "❌ Расписание не загружено. Проверьте настройки ITMO_LOGIN/ITMO_PASSWORD или SCHEDULE_JSON"

        current_week_type = get_current_week_type(target_date)

        # Находим нужную неделю в расписании
        for week in SCHEDULE_DATA['schedule']:
            if week['week'] == current_week_type:
                # Находим нужный день
                for day in week['days']:
                    if day['day'] == weekday_name:
                        classes = day['classes']

                        if not classes:
                            note = day.get('note', 'Нет занятий')
                            return f"📅 {weekday_name} ({date_formatted})\n\n{note}"

                        response = f"📅 {weekday_name} ({date_formatted})\n\n"

                        for class_item in classes:
                            response += format_class_info(class_item) + "\n"

                        return response

        return f"❌ Расписание для {weekday_name} не найдено"
    except ValueError:
        return "❌ Неверный формат даты. Используйте формат ДД.ММ"
    except Exception as e:
        logger.error(f"Ошибка получения расписания: {e}")
        return "❌ Ошибка при получении расписания"

def get_week_schedule():
    """Получает расписание на текущую неделю"""
    global schedule_fetcher
    
    current_time = get_moscow_time()
    days_since_monday = current_time.weekday()
    week_start = current_time - timedelta(days=days_since_monday)
    week_end = week_start + timedelta(days=6)

    # Если есть загрузчик с my.itmo.ru, используем его
    if schedule_fetcher:
        try:
            week_schedules = schedule_fetcher.get_week_schedule(week_start)
            
            response = f"📅 Расписание на неделю ({week_start.strftime('%d.%m')} - {week_end.strftime('%d.%m.%Y')})\n\n"
            
            for day_schedule in week_schedules:
                day_date = day_schedule.get('date', week_start)
                weekday_name = get_weekday_name(day_date)
                date_formatted = day_date.strftime('%d.%m')
                
                response += f"📅 {weekday_name} ({date_formatted}):\n"
                
                classes = day_schedule.get('classes', [])
                if not classes:
                    response += "   🆓 Нет занятий\n\n"
                else:
                    for class_item in classes:
                        class_text = format_class_info(class_item)
                        # Добавляем отступ для каждой строки
                        indented = '\n'.join(f"   {line}" for line in class_text.split('\n') if line.strip())
                        response += f"{indented}\n"
                    response += "\n"
            
            return response
        except Exception as e:
            logger.error(f"Ошибка получения недельного расписания с my.itmo.ru: {e}")
            # Пробуем использовать старый метод как fallback
            pass

    # Используем старый метод (из переменной окружения)
    if not SCHEDULE_DATA:
        return "❌ Расписание не загружено. Проверьте настройки ITMO_LOGIN/ITMO_PASSWORD или SCHEDULE_JSON"

    current_week_type = get_current_week_type()

    # Находим нужную неделю в расписании
    for week in SCHEDULE_DATA['schedule']:
        if week['week'] == current_week_type:
            response = f"📅 Расписание на неделю ({week_start.strftime('%d.%m')} - {week_end.strftime('%d.%m.%Y')})\n\n"

            for day in week['days']:
                day_name = day['day']
                classes = day['classes']

                response += f"📅 {day_name}:\n"

                if not classes:
                    note = day.get('note', 'Нет занятий')
                    response += f"   {note}\n\n"
                else:
                    for class_item in classes:
                        class_text = format_class_info(class_item)
                        # Добавляем отступ для каждой строки
                        indented = '\n'.join(f"   {line}" for line in class_text.split('\n') if line.strip())
                        response += f"{indented}\n"
                response += "\n"

            return response

    return "❌ Расписание не найдено"

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
            text='📝 Введите дату в формате ДД.ММ (например: 25.12)\n\nПосле ввода даты выберите следующее действие:',
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
    logger.error(f'Update {update} caused error {context.error}')
    if update and update.message:
        await update.message.reply_text('❌ Произошла ошибка. Попробуйте еще раз.')

async def create_application():
    """Создает и настраивает Telegram Application асинхронно"""
    logger.info("🚀 Инициализация Telegram бота ИТМО...")

    # Инициализируем загрузчик расписания
    load_schedule()

    # Проверяем, что хотя бы один источник расписания доступен
    global schedule_fetcher, SCHEDULE_DATA
    if not schedule_fetcher and not SCHEDULE_DATA:
        logger.error("❌ Не удалось инициализировать источник расписания")
        logger.error("Убедитесь, что установлены переменные окружения:")
        logger.error("  - ITMO_LOGIN и ITMO_PASSWORD (для получения с my.itmo.ru)")
        logger.error("  - или SCHEDULE_JSON (для использования статического расписания)")
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