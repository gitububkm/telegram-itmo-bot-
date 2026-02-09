#!/usr/bin/env python3
"""
Модуль для получения расписания с сайта my.itmo.ru
Авторизация и парсинг расписания
"""

import os
import re
import logging
import requests
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from bs4 import BeautifulSoup
from typing import Optional, Dict, List

logger = logging.getLogger(__name__)

class ITMOScheduleFetcher:
    """Класс для получения расписания с my.itmo.ru"""
    
    def __init__(self, login: str, password: str):
        """
        Инициализация с учетными данными
        
        Args:
            login: Логин ITMO ID
            password: Пароль ITMO ID
        """
        self.login = login
        self.password = password
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7',
            'Accept-Encoding': 'gzip, deflate, br',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1'
        })
        self.base_url = "https://my.itmo.ru"
        self.is_authenticated = False
        
    def authenticate(self) -> bool:
        """
        Авторизация на my.itmo.ru через ITMO ID
        
        Returns:
            True если авторизация успешна, False иначе
        """
        try:
            logger.info("🔐 Начало авторизации на my.itmo.ru...")
            
            # Шаг 1: Получаем страницу расписания (она перенаправит на авторизацию)
            schedule_url = f"{self.base_url}/schedule"
            response = self.session.get(schedule_url, timeout=10)
            
            if response.status_code != 200:
                logger.error(f"❌ Ошибка доступа к странице расписания: {response.status_code}")
                return False
            
            # Шаг 2: Ищем ссылку на авторизацию ITMO ID
            soup = BeautifulSoup(response.text, 'html.parser')
            
            # Ищем форму авторизации или ссылку на ITMO ID
            login_link = None
            for link in soup.find_all('a', href=True):
                href = link.get('href', '')
                if 'id.itmo.ru' in href or 'login' in href.lower():
                    login_link = href
                    break
            
            # Если не нашли прямую ссылку, пробуем найти форму
            if not login_link:
                # Пробуем найти форму авторизации
                form = soup.find('form')
                if form and form.get('action'):
                    login_link = form.get('action')
            
            # Если нашли ссылку на ITMO ID, переходим туда
            if login_link:
                if not login_link.startswith('http'):
                    login_link = f"{self.base_url}{login_link}"
                
                logger.info(f"🔗 Переход на страницу авторизации: {login_link}")
                auth_response = self.session.get(login_link, timeout=10)
                
                if auth_response.status_code == 200:
                    auth_soup = BeautifulSoup(auth_response.text, 'html.parser')
                    
                    # Ищем форму входа
                    login_form = auth_soup.find('form')
                    if login_form:
                        form_action = login_form.get('action', '')
                        if not form_action.startswith('http'):
                            form_action = f"{self.base_url}{form_action}" if form_action.startswith('/') else login_link
                        
                        # Собираем все скрытые поля формы
                        form_data = {}
                        for hidden_input in login_form.find_all('input', type='hidden'):
                            name = hidden_input.get('name')
                            value = hidden_input.get('value', '')
                            if name:
                                form_data[name] = value
                        
                        # Добавляем логин и пароль
                        username_field = login_form.find('input', {'type': 'text'}) or login_form.find('input', {'name': re.compile(r'user|login|email', re.I)})
                        password_field = login_form.find('input', {'type': 'password'})
                        
                        if username_field and password_field:
                            username_name = username_field.get('name', 'username')
                            password_name = password_field.get('name', 'password')
                            
                            form_data[username_name] = self.login
                            form_data[password_name] = self.password
                            
                            # Отправляем форму
                            logger.info("📤 Отправка данных авторизации...")
                            login_response = self.session.post(
                                form_action or login_link,
                                data=form_data,
                                allow_redirects=True,
                                timeout=10
                            )
                            
                            # Проверяем успешность авторизации
                            if login_response.status_code == 200:
                                # Проверяем, что мы авторизованы (проверяем наличие расписания)
                                test_response = self.session.get(schedule_url, timeout=10)
                                if 'schedule' in test_response.url.lower() or 'расписание' in test_response.text.lower():
                                    self.is_authenticated = True
                                    logger.info("✅ Авторизация успешна!")
                                    return True
            
            # Альтернативный метод: пробуем прямой API запрос (если есть)
            # Многие сайты используют API для получения расписания
            api_url = f"{self.base_url}/api/schedule"
            try:
                api_response = self.session.get(api_url, timeout=10)
                if api_response.status_code == 200:
                    self.is_authenticated = True
                    logger.info("✅ Авторизация через API успешна!")
                    return True
            except:
                pass
            
            logger.error("❌ Не удалось найти форму авторизации или авторизоваться")
            return False
            
        except requests.exceptions.RequestException as e:
            logger.error(f"❌ Ошибка сети при авторизации: {e}")
            return False
        except Exception as e:
            logger.error(f"❌ Неожиданная ошибка при авторизации: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return False
    
    def get_schedule_for_date(self, target_date: Optional[datetime] = None) -> Optional[Dict]:
        """
        Получает расписание на указанную дату
        
        Args:
            target_date: Дата для получения расписания (по умолчанию - сегодня)
            
        Returns:
            Словарь с расписанием или None в случае ошибки
        """
        if not self.is_authenticated:
            if not self.authenticate():
                logger.error("❌ Не удалось авторизоваться")
                return None
        
        try:
            if target_date is None:
                target_date = datetime.now(ZoneInfo("Europe/Moscow"))
            
            # Форматируем дату для запроса
            date_str = target_date.strftime("%Y-%m-%d")
            
            logger.info(f"📅 Запрос расписания на {date_str}...")
            
            # Пробуем получить через API
            api_url = f"{self.base_url}/api/schedule"
            params = {'date': date_str}
            
            response = self.session.get(api_url, params=params, timeout=10)
            
            if response.status_code == 200:
                try:
                    data = response.json()
                    if data:
                        logger.info("✅ Расписание получено через API")
                        return self._parse_api_schedule(data, target_date)
                except:
                    # Если не JSON, пробуем парсить HTML
                    pass
            
            # Если API не сработал, парсим HTML страницу
            schedule_url = f"{self.base_url}/schedule"
            params = {'date': date_str}
            response = self.session.get(schedule_url, params=params, timeout=10)
            
            if response.status_code == 200:
                return self._parse_html_schedule(response.text, target_date)
            else:
                logger.error(f"❌ Ошибка получения расписания: {response.status_code}")
                return None
                
        except requests.exceptions.RequestException as e:
            logger.error(f"❌ Ошибка сети при получении расписания: {e}")
            return None
        except Exception as e:
            logger.error(f"❌ Ошибка при получении расписания: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return None
    
    def _parse_api_schedule(self, data: Dict, target_date: datetime) -> Dict:
        """
        Парсит расписание из JSON API ответа
        
        Args:
            data: JSON данные от API
            target_date: Дата расписания
            
        Returns:
            Словарь с расписанием в формате для бота
        """
        # Адаптируем структуру данных под формат бота
        schedule = {
            'date': target_date,
            'classes': []
        }
        
        # Парсим структуру API (может отличаться, нужно адаптировать)
        if isinstance(data, list):
            for item in data:
                class_info = self._extract_class_info(item)
                if class_info:
                    schedule['classes'].append(class_info)
        elif isinstance(data, dict):
            # Пробуем разные возможные ключи
            for key in ['schedule', 'classes', 'lessons', 'items']:
                if key in data:
                    items = data[key] if isinstance(data[key], list) else [data[key]]
                    for item in items:
                        class_info = self._extract_class_info(item)
                        if class_info:
                            schedule['classes'].append(class_info)
        
        return schedule
    
    def _parse_html_schedule(self, html: str, target_date: datetime) -> Dict:
        """
        Парсит расписание из HTML страницы
        
        Args:
            html: HTML содержимое страницы
            target_date: Дата расписания
            
        Returns:
            Словарь с расписанием в формате для бота
        """
        soup = BeautifulSoup(html, 'html.parser')
        schedule = {
            'date': target_date,
            'classes': []
        }
        
        # Ищем таблицу или контейнер с расписанием
        # Структура может быть разной, пробуем разные варианты
        schedule_table = soup.find('table', class_=re.compile(r'schedule|table', re.I))
        if not schedule_table:
            schedule_table = soup.find('div', class_=re.compile(r'schedule|timetable', re.I))
        
        if schedule_table:
            # Парсим строки расписания
            rows = schedule_table.find_all('tr') if schedule_table.name == 'table' else schedule_table.find_all('div', class_=re.compile(r'row|item|lesson', re.I))
            
            for row in rows:
                class_info = self._parse_schedule_row(row)
                if class_info:
                    schedule['classes'].append(class_info)
        else:
            # Альтернативный метод: ищем все элементы с данными о парах
            lesson_elements = soup.find_all(['div', 'li', 'tr'], class_=re.compile(r'lesson|class|pair|subject', re.I))
            for element in lesson_elements:
                class_info = self._parse_schedule_row(element)
                if class_info:
                    schedule['classes'].append(class_info)
        
        return schedule
    
    def _parse_schedule_row(self, element) -> Optional[Dict]:
        """
        Парсит одну строку/элемент расписания
        
        Args:
            element: HTML элемент с информацией о паре
            
        Returns:
            Словарь с информацией о паре или None
        """
        try:
            class_info = {}
            
            # Ищем время
            time_elem = element.find(['span', 'div', 'td'], class_=re.compile(r'time|hour', re.I))
            if time_elem:
                class_info['time'] = time_elem.get_text(strip=True)
            
            # Ищем название предмета
            subject_elem = element.find(['span', 'div', 'td'], class_=re.compile(r'subject|name|title', re.I))
            if not subject_elem:
                # Пробуем найти по тексту
                text = element.get_text()
                if text:
                    lines = [line.strip() for line in text.split('\n') if line.strip()]
                    if lines:
                        class_info['subject'] = lines[0]
            
            if subject_elem:
                class_info['subject'] = subject_elem.get_text(strip=True)
            
            # Ищем аудиторию
            room_elem = element.find(['span', 'div', 'td'], class_=re.compile(r'room|audience|auditorium', re.I))
            if room_elem:
                class_info['room'] = room_elem.get_text(strip=True)
            
            # Ищем адрес
            address_elem = element.find(['span', 'div', 'td'], class_=re.compile(r'address|location|building', re.I))
            if address_elem:
                class_info['address'] = address_elem.get_text(strip=True)
            
            # Ищем преподавателя
            teacher_elem = element.find(['span', 'div', 'td'], class_=re.compile(r'teacher|instructor|lecturer', re.I))
            if teacher_elem:
                class_info['teacher'] = teacher_elem.get_text(strip=True)
            
            # Если нашли хотя бы предмет или время, возвращаем
            if 'subject' in class_info or 'time' in class_info:
                # Устанавливаем значения по умолчанию
                class_info.setdefault('time', 'Время не указано')
                class_info.setdefault('subject', 'Предмет не указан')
                class_info.setdefault('room', 'Аудитория не указана')
                class_info.setdefault('address', 'Адрес не указан')
                return class_info
            
            return None
            
        except Exception as e:
            logger.error(f"Ошибка парсинга строки расписания: {e}")
            return None
    
    def _extract_class_info(self, item: Dict) -> Optional[Dict]:
        """
        Извлекает информацию о паре из JSON объекта
        
        Args:
            item: JSON объект с данными о паре
            
        Returns:
            Словарь с информацией о паре или None
        """
        try:
            class_info = {}
            
            # Пробуем разные возможные ключи
            time_keys = ['time', 'start_time', 'time_start', 'begin_time', 'lesson_time']
            subject_keys = ['subject', 'name', 'title', 'lesson_name', 'discipline']
            room_keys = ['room', 'audience', 'auditorium', 'classroom', 'room_number']
            address_keys = ['address', 'location', 'building', 'address_name']
            teacher_keys = ['teacher', 'instructor', 'lecturer', 'teacher_name']
            
            for key in time_keys:
                if key in item:
                    class_info['time'] = str(item[key])
                    break
            
            for key in subject_keys:
                if key in item:
                    class_info['subject'] = str(item[key])
                    break
            
            for key in room_keys:
                if key in item:
                    class_info['room'] = str(item[key])
                    break
            
            for key in address_keys:
                if key in item:
                    class_info['address'] = str(item[key])
                    break
            
            for key in teacher_keys:
                if key in item:
                    class_info['teacher'] = str(item[key])
                    break
            
            if 'subject' in class_info or 'time' in class_info:
                class_info.setdefault('time', 'Время не указано')
                class_info.setdefault('subject', 'Предмет не указан')
                class_info.setdefault('room', 'Аудитория не указана')
                class_info.setdefault('address', 'Адрес не указан')
                return class_info
            
            return None
            
        except Exception as e:
            logger.error(f"Ошибка извлечения информации о паре: {e}")
            return None
    
    def get_week_schedule(self, start_date: Optional[datetime] = None) -> List[Dict]:
        """
        Получает расписание на неделю
        
        Args:
            start_date: Дата начала недели (по умолчанию - начало текущей недели)
            
        Returns:
            Список словарей с расписанием на каждый день недели
        """
        if start_date is None:
            start_date = datetime.now(ZoneInfo("Europe/Moscow"))
            # Находим начало недели (понедельник)
            days_since_monday = start_date.weekday()
            start_date = start_date - timedelta(days=days_since_monday)
        
        week_schedule = []
        
        for day_offset in range(7):
            day_date = start_date + timedelta(days=day_offset)
            day_schedule = self.get_schedule_for_date(day_date)
            if day_schedule:
                week_schedule.append(day_schedule)
        
        return week_schedule
