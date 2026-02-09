#!/usr/bin/env python3
"""
Модуль для получения расписания с сайта my.itmo.ru
Авторизация через OAuth и парсинг расписания
"""

import os
import re
import logging
import requests
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from bs4 import BeautifulSoup
from typing import Optional, Dict, List
from urllib.parse import urlparse, parse_qs, urljoin

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
        self.id_url = "https://id.itmo.ru"
        self.is_authenticated = False
        
    def authenticate(self) -> bool:
        """
        Авторизация на my.itmo.ru через OAuth (id.itmo.ru)
        
        Returns:
            True если авторизация успешна, False иначе
        """
        try:
            logger.info("🔐 Начало авторизации на my.itmo.ru через OAuth...")
            
            # Шаг 1: Получаем страницу расписания (она перенаправит на авторизацию)
            schedule_url = f"{self.base_url}/schedule"
            response = self.session.get(schedule_url, timeout=10, allow_redirects=True)
            
            # Шаг 2: Ищем ссылку на OAuth авторизацию или получаем её из редиректа
            oauth_url = None
            
            # Проверяем, есть ли в ответе ссылка на id.itmo.ru
            if 'id.itmo.ru' in response.url:
                oauth_url = response.url
            else:
                # Парсим HTML и ищем ссылку на авторизацию
                soup = BeautifulSoup(response.text, 'html.parser')
                
                # Ищем ссылку на OAuth
                for link in soup.find_all('a', href=True):
                    href = link.get('href', '')
                    if 'id.itmo.ru' in href and 'openid-connect' in href:
                        oauth_url = href
                        break
                
                # Если не нашли, пробуем найти форму или редирект
                if not oauth_url:
                    # Ищем meta refresh или JavaScript редирект
                    meta_refresh = soup.find('meta', {'http-equiv': 'refresh'})
                    if meta_refresh:
                        content = meta_refresh.get('content', '')
                        if 'url=' in content:
                            oauth_url = content.split('url=')[1]
            
            if not oauth_url:
                # Пробуем стандартный OAuth URL
                oauth_url = f"{self.id_url}/auth/realms/itmo/protocol/openid-connect/auth"
                params = {
                    'protocol': 'oauth2',
                    'response_type': 'code',
                    'client_id': 'student-personal-cabinet',
                    'redirect_uri': f'{self.base_url}/login/callback',
                    'scope': 'openid profile',
                    'code_challenge_method': 'S256'
                }
                # Получаем страницу авторизации
                response = self.session.get(oauth_url, params=params, timeout=10)
                oauth_url = response.url
            
            logger.info(f"🔗 Переход на страницу OAuth авторизации: {oauth_url}")
            
            # Шаг 3: Получаем страницу входа
            auth_response = self.session.get(oauth_url, timeout=10)
            
            if auth_response.status_code != 200:
                logger.error(f"❌ Ошибка доступа к странице авторизации: {auth_response.status_code}")
                return False
            
            # Шаг 4: Парсим форму входа
            auth_soup = BeautifulSoup(auth_response.text, 'html.parser')
            
            # Ищем форму входа
            login_form = auth_soup.find('form')
            if not login_form:
                # Пробуем найти форму по id или class
                login_form = auth_soup.find('form', {'id': re.compile(r'login|auth', re.I)}) or \
                            auth_soup.find('form', {'class': re.compile(r'login|auth', re.I)})
            
            if not login_form:
                logger.error("❌ Не найдена форма авторизации")
                return False
            
            # Получаем action формы
            form_action = login_form.get('action', '')
            if not form_action.startswith('http'):
                form_action = urljoin(self.id_url, form_action)
            
            # Собираем все скрытые поля формы
            form_data = {}
            for hidden_input in login_form.find_all('input', type='hidden'):
                name = hidden_input.get('name')
                value = hidden_input.get('value', '')
                if name:
                    form_data[name] = value
            
            # Ищем поля для логина и пароля
            username_field = login_form.find('input', {'type': 'text'}) or \
                           login_form.find('input', {'name': re.compile(r'user|login|email|username', re.I)}) or \
                           login_form.find('input', {'id': re.compile(r'user|login|email|username', re.I)})
            
            password_field = login_form.find('input', {'type': 'password'})
            
            if not username_field or not password_field:
                logger.error("❌ Не найдены поля для логина или пароля")
                return False
            
            username_name = username_field.get('name') or username_field.get('id', 'username')
            password_name = password_field.get('name') or password_field.get('id', 'password')
            
            form_data[username_name] = self.login
            form_data[password_name] = self.password
            
            # Отправляем форму авторизации
            logger.info("📤 Отправка данных авторизации...")
            login_response = self.session.post(
                form_action,
                data=form_data,
                allow_redirects=True,
                timeout=10
            )
            
            # Проверяем успешность авторизации
            # После успешной авторизации должен быть редирект на my.itmo.ru
            if login_response.status_code in [200, 302]:
                # Проверяем, что мы попали на my.itmo.ru
                final_url = login_response.url
                if 'my.itmo.ru' in final_url or login_response.history:
                    # Проверяем доступ к расписанию
                    test_response = self.session.get(f"{self.base_url}/schedule", timeout=10)
                    if test_response.status_code == 200 and 'schedule' in test_response.url:
                        self.is_authenticated = True
                        logger.info("✅ Авторизация успешна!")
                        return True
            
            logger.error("❌ Авторизация не удалась - проверьте логин и пароль")
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
            
            # Получаем страницу расписания с параметром даты
            schedule_url = f"{self.base_url}/schedule"
            params = {'date': date_str}
            response = self.session.get(schedule_url, params=params, timeout=10)
            
            if response.status_code != 200:
                logger.error(f"❌ Ошибка получения расписания: {response.status_code}")
                return None
            
            return self._parse_html_schedule(response.text, target_date)
                
        except requests.exceptions.RequestException as e:
            logger.error(f"❌ Ошибка сети при получении расписания: {e}")
            return None
        except Exception as e:
            logger.error(f"❌ Ошибка при получении расписания: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return None
    
    def _parse_html_schedule(self, html: str, target_date: datetime) -> Dict:
        """
        Парсит расписание из HTML страницы по структуре my.itmo.ru
        
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
        
        # Ищем все элементы с классом "lesson" (структура из скриншота)
        lesson_elements = soup.find_all('div', class_=re.compile(r'lesson', re.I))
        
        for lesson_elem in lesson_elements:
            class_info = self._parse_lesson_element(lesson_elem)
            if class_info:
                schedule['classes'].append(class_info)
        
        # Если не нашли через класс lesson, пробуем альтернативные селекторы
        if not schedule['classes']:
            # Ищем по структуре времени
            time_elements = soup.find_all('div', class_=re.compile(r'time', re.I))
            for time_elem in time_elements:
                # Ищем родительский элемент с информацией о паре
                parent = time_elem.find_parent('div', class_=re.compile(r'lesson|schedule|calendar', re.I))
                if parent:
                    class_info = self._parse_lesson_element(parent)
                    if class_info:
                        schedule['classes'].append(class_info)
        
        return schedule
    
    def _parse_lesson_element(self, element) -> Optional[Dict]:
        """
        Парсит один элемент пары по структуре my.itmo.ru
        
        Структура из скриншота:
        - div.time с div.time-start и div.time-end
        - div.title.max-lines-2 - название предмета
        - div.teacher с a - преподаватель
        - div.address с div.max-lines-1 (аудитория) и div.building (адрес)
        
        Args:
            element: HTML элемент с информацией о паре
            
        Returns:
            Словарь с информацией о паре или None
        """
        try:
            class_info = {}
            
            # Ищем время начала и конца
            time_elem = element.find('div', class_=re.compile(r'time', re.I))
            if time_elem:
                time_start_elem = time_elem.find('div', class_=re.compile(r'time-start', re.I))
                time_end_elem = time_elem.find('div', class_=re.compile(r'time-end', re.I))
                
                if time_start_elem and time_end_elem:
                    time_start = time_start_elem.get_text(strip=True)
                    time_end = time_end_elem.get_text(strip=True)
                    class_info['time'] = f"{time_start}-{time_end}"
                elif time_elem:
                    # Если нет отдельных элементов, берем весь текст
                    time_text = time_elem.get_text(strip=True)
                    if time_text:
                        class_info['time'] = time_text
            
            # Ищем название предмета
            title_elem = element.find('div', class_=re.compile(r'title', re.I))
            if title_elem:
                class_info['subject'] = title_elem.get_text(strip=True)
            
            # Ищем преподавателя
            teacher_elem = element.find('div', class_=re.compile(r'teacher', re.I))
            if teacher_elem:
                teacher_link = teacher_elem.find('a')
                if teacher_link:
                    class_info['teacher'] = teacher_link.get_text(strip=True)
                else:
                    # Если нет ссылки, берем весь текст
                    teacher_text = teacher_elem.get_text(strip=True)
                    # Убираем иконку пользователя из текста
                    teacher_text = re.sub(r'^[^\w]+', '', teacher_text).strip()
                    if teacher_text:
                        class_info['teacher'] = teacher_text
            
            # Ищем адрес и аудиторию
            address_elem = element.find('div', class_=re.compile(r'address', re.I))
            if address_elem:
                # Ищем аудиторию (обычно в div.max-lines-1)
                room_elem = address_elem.find('div', class_=re.compile(r'max-lines-1', re.I))
                if room_elem:
                    room_text = room_elem.get_text(strip=True)
                    # Убираем "ауд." если есть, оставляем только номер
                    room_text = re.sub(r'^ауд\.?\s*', '', room_text, flags=re.I).strip()
                    class_info['room'] = room_text if room_text else 'Аудитория не указана'
                else:
                    # Пробуем найти по другому селектору
                    room_text = address_elem.get_text(strip=True)
                    # Ищем паттерн "ауд. XXX"
                    room_match = re.search(r'ауд\.?\s*(\d+)', room_text, re.I)
                    if room_match:
                        class_info['room'] = room_match.group(1)
                
                # Ищем адрес здания (div.building)
                building_elem = address_elem.find('div', class_=re.compile(r'building', re.I))
                if building_elem:
                    class_info['address'] = building_elem.get_text(strip=True)
                else:
                    # Пробуем извлечь адрес из всего текста
                    address_text = address_elem.get_text(strip=True)
                    # Убираем аудиторию из адреса
                    address_text = re.sub(r'ауд\.?\s*\d+[,\s]*', '', address_text, flags=re.I).strip()
                    if address_text and len(address_text) > 10:  # Адрес обычно длиннее
                        class_info['address'] = address_text
            
            # Устанавливаем значения по умолчанию
            class_info.setdefault('time', 'Время не указано')
            class_info.setdefault('subject', 'Предмет не указан')
            class_info.setdefault('room', 'Аудитория не указана')
            class_info.setdefault('address', 'Адрес не указан')
            
            # Если нашли хотя бы предмет или время, возвращаем
            if 'subject' in class_info and class_info['subject'] != 'Предмет не указан':
                return class_info
            
            return None
            
        except Exception as e:
            logger.error(f"Ошибка парсинга элемента пары: {e}")
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
