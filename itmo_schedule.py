#!/usr/bin/env python3
"""
Модуль для получения расписания с сайта my.itmo.ru
Авторизация через OAuth и парсинг расписания
"""

import os
import re
import logging
import requests
import secrets
import base64
import hashlib
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
        # requests автоматически обрабатывает gzip/deflate, но нужно убедиться
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7',
            'Accept-Encoding': 'gzip, deflate',  # Убираем br (Brotli) - requests может не поддерживать
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1'
        })
        # Убеждаемся, что requests автоматически декодирует ответы
        # requests автоматически обрабатывает gzip/deflate через urllib3
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
            
            # Шаг 0: Проверяем, может быть уже авторизованы
            logger.info("🔍 Проверка текущего статуса авторизации...")
            test_response = self.session.get(f"{self.base_url}/schedule", timeout=10, allow_redirects=False)
            
            # Если получили успешный ответ и не редирект на авторизацию - уже авторизованы
            if test_response.status_code == 200:
                # Проверяем содержимое страницы - может быть это страница расписания
                if 'schedule' in test_response.url.lower() or 'my.itmo.ru/schedule' in test_response.url:
                    # Парсим HTML, чтобы убедиться, что это действительно страница расписания
                    soup = BeautifulSoup(test_response.text, 'html.parser')
                    # Ищем признаки страницы расписания (не страницы авторизации)
                    if 'id.itmo.ru' not in test_response.url and 'login' not in test_response.url.lower():
                        # Проверяем, есть ли на странице элементы расписания
                        schedule_indicators = soup.find_all(['div', 'section'], class_=re.compile(r'schedule|lesson|class', re.I))
                        if schedule_indicators or 'schedule' in test_response.text.lower()[:1000]:
                            self.is_authenticated = True
                            logger.info("✅ Уже авторизован! Пропускаем процесс авторизации.")
                            return True
            
            # Шаг 1: Получаем страницу расписания (она перенаправит на авторизацию)
            schedule_url = f"{self.base_url}/schedule"
            response = self.session.get(schedule_url, timeout=10, allow_redirects=True)
            
            logger.info(f"📍 URL после редиректа: {response.url}")
            
            # Шаг 2: Ищем ссылку на OAuth авторизацию или получаем её из редиректа
            oauth_url = None
            
            # Проверяем, есть ли в ответе ссылка на id.itmo.ru
            if 'id.itmo.ru' in response.url:
                oauth_url = response.url
                logger.info(f"✅ Найден OAuth URL из редиректа: {oauth_url}")
            else:
                # Парсим HTML и ищем ссылку на авторизацию
                soup = BeautifulSoup(response.text, 'html.parser')
                
                # Ищем ссылку на OAuth
                for link in soup.find_all('a', href=True):
                    href = link.get('href', '')
                    if 'id.itmo.ru' in href and 'openid-connect' in href:
                        oauth_url = href
                        logger.info(f"✅ Найден OAuth URL из ссылки: {oauth_url}")
                        break
                
                # Если не нашли, пробуем найти форму или редирект
                if not oauth_url:
                    # Ищем meta refresh или JavaScript редирект
                    meta_refresh = soup.find('meta', {'http-equiv': 'refresh'})
                    if meta_refresh:
                        content = meta_refresh.get('content', '')
                        if 'url=' in content:
                            oauth_url = content.split('url=')[1]
                            logger.info(f"✅ Найден OAuth URL из meta refresh: {oauth_url}")
            
            if not oauth_url:
                # Генерируем PKCE параметры для OAuth (требуется для безопасности)
                code_verifier = base64.urlsafe_b64encode(secrets.token_bytes(32)).decode('utf-8').rstrip('=')
                code_challenge = base64.urlsafe_b64encode(
                    hashlib.sha256(code_verifier.encode('utf-8')).digest()
                ).decode('utf-8').rstrip('=')
                
                # Пробуем стандартный OAuth URL с PKCE
                oauth_url = f"{self.id_url}/auth/realms/itmo/protocol/openid-connect/auth"
                params = {
                    'protocol': 'oauth2',
                    'response_type': 'code',
                    'client_id': 'student-personal-cabinet',
                    'redirect_uri': f'{self.base_url}/login/callback',
                    'scope': 'openid profile',
                    'code_challenge_method': 'S256',
                    'code_challenge': code_challenge
                }
                logger.info(f"🔗 Используем стандартный OAuth URL с PKCE параметрами")
                # Получаем страницу авторизации
                response = self.session.get(oauth_url, params=params, timeout=10, allow_redirects=False)
                
                # Если редирект, проверяем URL
                if response.status_code in [302, 301, 303, 307, 308]:
                    redirect_url = response.headers.get('Location', '')
                    if redirect_url:
                        oauth_url = redirect_url if redirect_url.startswith('http') else urljoin(self.id_url, redirect_url)
                    else:
                        oauth_url = response.url
                else:
                    oauth_url = response.url
                
                logger.info(f"📍 Финальный OAuth URL: {oauth_url}")
                
                # Проверяем, нет ли ошибки в URL
                if 'error=' in oauth_url:
                    error_desc = parse_qs(urlparse(oauth_url).query).get('error_description', [])
                    logger.error(f"❌ OAuth ошибка в URL: {oauth_url}")
                    if error_desc:
                        logger.error(f"   Описание ошибки: {error_desc[0]}")
                    return False
            
            # Шаг 3: Получаем страницу входа
            auth_response = self.session.get(oauth_url, timeout=10, allow_redirects=True)
            
            # Проверяем, может быть уже авторизованы и получили редирект на расписание
            if auth_response.status_code in [200, 302, 303, 307, 308]:
                final_url = auth_response.url
                # Если попали на my.itmo.ru (не на id.itmo.ru) - возможно уже авторизованы
                if 'my.itmo.ru' in final_url and 'id.itmo.ru' not in final_url:
                    # Проверяем доступ к расписанию
                    test_response = self.session.get(f"{self.base_url}/schedule", timeout=10)
                    if test_response.status_code == 200 and 'schedule' in test_response.url:
                        self.is_authenticated = True
                        logger.info("✅ Уже авторизован! Получен доступ к расписанию.")
                        return True
            
            # Проверяем, нет ли ошибки OAuth в финальном URL
            if 'error=' in auth_response.url:
                error_params = parse_qs(urlparse(auth_response.url).query)
                error = error_params.get('error', ['unknown'])[0]
                error_desc = error_params.get('error_description', [''])[0]
                logger.error(f"❌ OAuth ошибка после редиректа: {error}")
                logger.error(f"   Описание: {error_desc}")
                logger.error(f"   URL: {auth_response.url}")
                return False
            
            if auth_response.status_code != 200:
                logger.error(f"❌ Ошибка доступа к странице авторизации: {auth_response.status_code}")
                logger.error(f"URL: {auth_response.url}")
                logger.error(f"Response headers: {dict(auth_response.headers)}")
                if auth_response.text:
                    logger.error(f"Response body (первые 500 символов): {auth_response.text[:500]}")
                return False
            
            logger.info(f"✅ Получена страница авторизации: {auth_response.url}")
            
            # Проверяем содержимое страницы - может быть это уже страница расписания или успешной авторизации
            soup_check = BeautifulSoup(auth_response.text, 'html.parser')
            # Ищем признаки того, что мы уже на странице my.itmo.ru (не на странице авторизации)
            if 'my.itmo.ru' in auth_response.url and 'schedule' in auth_response.url.lower():
                self.is_authenticated = True
                logger.info("✅ Уже авторизован! На странице расписания.")
                return True
            
            # Проверяем кодировку и декодируем ответ
            if auth_response.encoding is None or auth_response.encoding.lower() not in ['utf-8', 'utf8']:
                auth_response.encoding = 'utf-8'
            
            # Логируем информацию о ответе для отладки
            logger.debug(f"Content-Type: {auth_response.headers.get('Content-Type')}")
            logger.debug(f"Encoding: {auth_response.encoding}")
            logger.debug(f"Длина ответа: {len(auth_response.text)} символов")
            
            # Шаг 4: Парсим форму входа
            try:
                auth_soup = BeautifulSoup(auth_response.text, 'html.parser')
            except Exception as e:
                logger.error(f"❌ Ошибка парсинга HTML страницы авторизации: {e}")
                logger.error(f"Первые 500 символов ответа: {auth_response.text[:500]}")
                return False
            
            # Ищем форму входа - пробуем разные варианты
            login_form = None
            
            # Вариант 1: Простая форма
            login_form = auth_soup.find('form')
            
            # Вариант 2: Форма по id (Keycloak часто использует kc-form-login)
            if not login_form:
                login_form = auth_soup.find('form', {'id': re.compile(r'login|auth|kc-form|kc-login|kc-form-login', re.I)})
            
            # Вариант 3: Форма по class (Keycloak использует различные классы)
            if not login_form:
                login_form = auth_soup.find('form', {'class': re.compile(r'login|auth|kc-form|kc-login', re.I)})
            
            # Вариант 4: Форма по action (ищем login-actions/authenticate)
            if not login_form:
                for form in auth_soup.find_all('form'):
                    action = form.get('action', '')
                    if 'login' in action.lower() or 'auth' in action.lower() or 'authenticate' in action.lower():
                        login_form = form
                        logger.info(f"✅ Найдена форма по action: {action}")
                        break
            
            # Вариант 5: Ищем форму с полем password (самый надежный способ)
            if not login_form:
                for form in auth_soup.find_all('form'):
                    password_input = form.find('input', {'type': 'password'})
                    if password_input:
                        login_form = form
                        logger.info("✅ Найдена форма по наличию поля password")
                        break
            
            # Вариант 6: Ищем форму в div с классом login или auth
            if not login_form:
                login_div = auth_soup.find('div', {'class': re.compile(r'login|auth|kc-login', re.I)})
                if login_div:
                    login_form = login_div.find('form')
                    if login_form:
                        logger.info("✅ Найдена форма внутри div с классом login/auth")
            
            # Вариант 6: Пробуем найти данные авторизации в JavaScript (Keycloak SPA)
            if not login_form:
                # Keycloak использует JavaScript для рендеринга формы
                # Пробуем найти данные в kcContext или других скриптах
                script_tags = auth_soup.find_all('script')
                auth_action_url = None
                tab_id = None
                session_code = None
                
                for script in script_tags:
                    script_text = script.string or ''
                    if not script_text:
                        continue
                    
                    # Ищем tab_id и session_code в kcContext
                    # Вариант 1: Прямое значение в объекте (tab_id: "value")
                    tab_id_match = re.search(r'tab_id["\']?\s*:\s*["\']([^"\']+)["\']', script_text)
                    session_match = re.search(r'session_code["\']?\s*:\s*["\']([^"\']+)["\']', script_text)
                    
                    if tab_id_match:
                        tab_id = tab_id_match.group(1)
                    if session_match:
                        session_code = session_match.group(1)
                    
                    # Вариант 2: В query строке (tab_id=value&session_code=value)
                    if not tab_id or not session_code:
                        # Ищем query строку с параметрами
                        query_match = re.search(r'["\']query["\']?\s*:\s*["\']([^"\']+)["\']', script_text)
                        if query_match:
                            query_string = query_match.group(1)
                            # Извлекаем tab_id из query
                            tab_id_query = re.search(r'tab_id=([^&"\']+)', query_string)
                            if tab_id_query:
                                tab_id = tab_id_query.group(1)
                            # Извлекаем session_code из query
                            session_query = re.search(r'session_code=([^&"\']+)', query_string)
                            if session_query:
                                session_code = session_query.group(1)
                    
                    # Вариант 3: В rawQuery строке
                    if not tab_id or not session_code:
                        raw_query_match = re.search(r'["\']rawQuery["\']?\s*:\s*["\']([^"\']+)["\']', script_text)
                        if raw_query_match:
                            query_string = raw_query_match.group(1)
                            tab_id_query = re.search(r'tab_id=([^&"\']+)', query_string)
                            if tab_id_query:
                                tab_id = tab_id_query.group(1)
                            session_query = re.search(r'session_code=([^&"\']+)', query_string)
                            if session_query:
                                session_code = session_query.group(1)
                    
                    # Ищем URL авторизации
                    if 'login-actions' in script_text or 'authenticate' in script_text:
                        # Ищем различные варианты URL
                        # Вариант 1: Полный URL в кавычках
                        url_match = re.search(r'["\'](https?://[^"\']*login-actions[^"\']*)["\']', script_text)
                        if url_match:
                            auth_action_url = url_match.group(1)
                        else:
                            # Вариант 2: Относительный путь
                            url_match = re.search(r'["\']([^"\']*login-actions[^"\']*)["\']', script_text)
                            if url_match:
                                auth_action_url = url_match.group(1)
                                # Убираем экранированные слеши
                                auth_action_url = auth_action_url.replace('\\/', '/')
                                # Если путь начинается с /, добавляем базовый URL
                                if auth_action_url.startswith('/'):
                                    auth_action_url = f"{self.id_url}{auth_action_url}"
                                elif not auth_action_url.startswith('http'):
                                    # Если путь без начального /, добавляем базовый URL и /
                                    auth_action_url = f"{self.id_url}/{auth_action_url}"
                
                # Логируем результаты поиска
                if tab_id:
                    logger.info(f"✅ Найден tab_id: {tab_id[:30]}...")
                else:
                    logger.warning("⚠️ tab_id не найден в JavaScript")
                
                if session_code:
                    logger.info(f"✅ Найден session_code: {session_code[:30]}...")
                else:
                    logger.warning("⚠️ session_code не найден в JavaScript")
                
                # Если нашли данные, пробуем прямую авторизацию
                if tab_id and session_code:
                    # Формируем URL для авторизации
                    if not auth_action_url:
                        auth_action_url = f"{self.id_url}/auth/realms/itmo/login-actions/authenticate"
                    else:
                        # Убираем экранированные слеши, если есть
                        auth_action_url = auth_action_url.replace('\\/', '/')
                        # Убеждаемся, что URL полный
                        if not auth_action_url.startswith('http'):
                            if auth_action_url.startswith('/'):
                                auth_action_url = f"{self.id_url}{auth_action_url}"
                            else:
                                auth_action_url = f"{self.id_url}/{auth_action_url}"
                    
                    logger.info(f"🔗 Найдены данные Keycloak: tab_id={tab_id[:20]}..., session_code={session_code[:20]}...")
                    logger.info(f"🔗 URL авторизации: {auth_action_url}")
                    return self._direct_keycloak_auth_with_params(auth_action_url, tab_id, session_code)
                
                # Если не нашли tab_id и session_code, не пытаемся напрямую обращаться к authenticate endpoint
                # Вместо этого пробуем найти форму через другие методы или возвращаем ошибку
                logger.warning("⚠️ Не найдены tab_id и session_code для прямой авторизации Keycloak")
            
            if not login_form:
                # Логируем структуру страницы для отладки
                forms = auth_soup.find_all('form')
                logger.error(f"❌ Не найдена форма авторизации. Найдено форм на странице: {len(forms)}")
                if forms:
                    for i, form in enumerate(forms):
                        logger.error(f"  Форма {i+1}: id={form.get('id')}, class={form.get('class')}, action={form.get('action')}")
                
                # Проверяем, может быть это страница с ошибкой или редиректом
                if 'error' in auth_response.url.lower() or 'error' in auth_response.text.lower()[:500]:
                    logger.error("⚠️ Похоже, что на странице есть ошибка")
                
                # Проверяем, может быть это JavaScript-приложение (SPA)
                scripts = auth_soup.find_all('script')
                if scripts:
                    logger.info(f"Найдено {len(scripts)} script тегов - возможно, это SPA приложение")
                    # Ищем упоминания Keycloak или React
                    for script in scripts[:3]:  # Проверяем первые 3 скрипта
                        script_text = script.string or ''
                        if script_text and ('keycloak' in script_text.lower() or 'react' in script_text.lower()):
                            logger.info("Обнаружено Keycloak/React приложение - форма может рендериться через JavaScript")
                
                # Сохраняем HTML для отладки (первые 2000 символов)
                logger.error(f"HTML страницы (первые 2000 символов): {auth_response.text[:2000]}")
                return False
            
            logger.info(f"✅ Найдена форма авторизации: action={login_form.get('action')}")
            
            # Получаем action формы
            form_action = login_form.get('action', '')
            if not form_action:
                # Если action пустой, используем текущий URL
                form_action = auth_response.url
            elif not form_action.startswith('http'):
                form_action = urljoin(self.id_url, form_action)
            
            logger.info(f"📤 Action формы: {form_action}")
            
            # Собираем все скрытые поля формы
            form_data = {}
            for hidden_input in login_form.find_all('input', type='hidden'):
                name = hidden_input.get('name')
                value = hidden_input.get('value', '')
                if name:
                    form_data[name] = value
                    logger.debug(f"  Скрытое поле: {name} = {value[:50] if len(value) > 50 else value}")
            
            # Ищем поля для логина и пароля - пробуем разные варианты
            username_field = None
            password_field = None
            
            # Вариант 1: По типу
            username_field = login_form.find('input', {'type': 'text'})
            password_field = login_form.find('input', {'type': 'password'})
            
            # Вариант 2: По name
            if not username_field:
                username_field = login_form.find('input', {'name': re.compile(r'user|login|email|username', re.I)})
            if not password_field:
                password_field = login_form.find('input', {'name': re.compile(r'password|pass', re.I)})
            
            # Вариант 3: По id
            if not username_field:
                username_field = login_form.find('input', {'id': re.compile(r'user|login|email|username', re.I)})
            if not password_field:
                password_field = login_form.find('input', {'id': re.compile(r'password|pass', re.I)})
            
            # Вариант 4: Любое текстовое поле и любое поле пароля
            if not username_field:
                for inp in login_form.find_all('input'):
                    inp_type = inp.get('type', '').lower()
                    if inp_type in ['text', 'email']:
                        username_field = inp
                        break
            
            if not password_field:
                password_field = login_form.find('input', {'type': 'password'})
            
            if not username_field or not password_field:
                logger.error("❌ Не найдены поля для логина или пароля")
                logger.error(f"  Найдено input полей: {len(login_form.find_all('input'))}")
                for inp in login_form.find_all('input'):
                    logger.error(f"    Input: type={inp.get('type')}, name={inp.get('name')}, id={inp.get('id')}")
                return False
            
            username_name = username_field.get('name') or username_field.get('id', 'username')
            password_name = password_field.get('name') or password_field.get('id', 'password')
            
            logger.info(f"✅ Найдены поля: username={username_name}, password={password_name}")
            
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
    
    def _direct_keycloak_auth_with_params(self, auth_url: str, tab_id: Optional[str] = None, session_code: Optional[str] = None) -> bool:
        """
        Прямая авторизация через Keycloak с параметрами из JavaScript контекста
        
        Args:
            auth_url: URL для авторизации
            tab_id: Tab ID из kcContext
            session_code: Session code из kcContext
            
        Returns:
            True если авторизация успешна
        """
        try:
            logger.info(f"🔐 Попытка прямой авторизации через Keycloak: {auth_url}")
            
            # Проверяем, что у нас есть необходимые параметры
            if not tab_id or not session_code:
                logger.error("❌ Недостаточно параметров для прямой авторизации Keycloak (требуются tab_id и session_code)")
                return False
            
            # Формируем параметры запроса
            params = {
                'tab_id': tab_id,
                'session_code': session_code
            }
            
            # Получаем страницу авторизации с параметрами
            # Пробуем сначала без редиректов, чтобы увидеть, что возвращает сервер
            response = self.session.get(auth_url, params=params, timeout=10, allow_redirects=False)
            
            # Если редирект, следуем ему
            if response.status_code in [302, 301, 303, 307, 308]:
                redirect_url = response.headers.get('Location', '')
                if redirect_url:
                    if not redirect_url.startswith('http'):
                        redirect_url = urljoin(self.id_url, redirect_url)
                    logger.info(f"📍 Редирект на: {redirect_url}")
                    response = self.session.get(redirect_url, timeout=10, allow_redirects=True)
            
            if response.status_code != 200:
                # Если ошибка 400, возможно сессия истекла или параметры неверны
                # Проверяем, может быть уже авторизованы через другой способ
                if response.status_code == 400:
                    logger.warning("⚠️ Ошибка 400 - возможно сессия истекла или параметры неверны")
                    logger.warning("🔍 Проверяем, может быть уже авторизованы...")
                    # Пробуем проверить доступ к расписанию
                    test_response = self.session.get(f"{self.base_url}/schedule", timeout=10, allow_redirects=False)
                    if test_response.status_code == 200:
                        self.is_authenticated = True
                        logger.info("✅ Уже авторизован! Ошибка 400 была ложной тревогой.")
                        return True
                
                logger.error(f"❌ Ошибка доступа к странице авторизации: {response.status_code}")
                logger.error(f"URL: {response.url}")
                if response.status_code == 400:
                    logger.error("⚠️ Ошибка 400 обычно означает неверные параметры запроса")
                    logger.error(f"Параметры запроса: {params}")
                return False
            
            # Парсим URL для извлечения параметров
            from urllib.parse import urlparse, parse_qs
            parsed_url = urlparse(auth_url)
            url_params = parse_qs(parsed_url.query)
            
            # Извлекаем параметры из URL
            execution = url_params.get('execution', [None])[0]
            client_id = url_params.get('client_id', [None])[0]
            client_data = url_params.get('client_data', [None])[0]
            
            # Проверяем, может быть уже авторизованы - проверяем содержимое страницы
            soup_check = BeautifulSoup(response.text, 'html.parser')
            # Если на странице нет элементов авторизации, возможно уже авторизованы
            if 'my.itmo.ru' in response.url and 'id.itmo.ru' not in response.url:
                # Проверяем доступ к расписанию
                test_response = self.session.get(f"{self.base_url}/schedule", timeout=10)
                if test_response.status_code == 200:
                    self.is_authenticated = True
                    logger.info("✅ Уже авторизован! Проверено через доступ к расписанию.")
                    return True
            
            # Пробуем найти форму в HTML (на случай, если она есть)
            soup = BeautifulSoup(response.text, 'html.parser')
            form = soup.find('form')
            
            # Если форма не найдена (SPA приложение), используем прямой POST
            if not form:
                logger.info("⚠️ Форма не найдена в HTML (SPA приложение), используем прямой POST")
                
                # Формируем URL для POST запроса (убираем query параметры из URL)
                post_url = f"{self.id_url}/auth/realms/itmo/login-actions/authenticate"
                
                # Формируем данные для POST запроса
                form_data = {
                    'username': self.login,
                    'password': self.password,
                    'tab_id': tab_id,
                    'session_code': session_code,
                }
                
                # Добавляем параметры из URL, если они есть
                if execution:
                    form_data['execution'] = execution
                if client_id:
                    form_data['client_id'] = client_id
                if client_data:
                    form_data['client_data'] = client_data
                
                # Добавляем стандартные поля для Keycloak
                form_data['credentialId'] = ''
                
                logger.info("📤 Отправка данных авторизации через прямой POST...")
                login_response = self.session.post(
                    post_url,
                    data=form_data,
                    params={
                        'tab_id': tab_id,
                        'session_code': session_code
                    },
                    allow_redirects=True,
                    timeout=10
                )
            else:
                # Стандартный путь через форму (если она найдена)
                form_action = form.get('action', '')
                if not form_action:
                    form_action = response.url
                elif not form_action.startswith('http'):
                    form_action = urljoin(self.id_url, form_action)
                
                # Собираем данные формы
                form_data = {}
                for hidden_input in form.find_all('input', type='hidden'):
                    name = hidden_input.get('name')
                    value = hidden_input.get('value', '')
                    if name:
                        form_data[name] = value
                
                # Ищем поля логина и пароля
                username_field = form.find('input', {'type': 'text'}) or form.find('input', {'name': re.compile(r'user|login|email', re.I)})
                password_field = form.find('input', {'type': 'password'})
                
                if not username_field or not password_field:
                    logger.error("❌ Не найдены поля для логина или пароля")
                    return False
                
                username_name = username_field.get('name') or username_field.get('id', 'username')
                password_name = password_field.get('name') or password_field.get('id', 'password')
                
                form_data[username_name] = self.login
                form_data[password_name] = self.password
                
                # Отправляем форму
                logger.info("📤 Отправка данных авторизации через форму...")
                login_response = self.session.post(
                    form_action,
                    data=form_data,
                    allow_redirects=True,
                    timeout=10
                )
            
            # Проверяем успешность
            logger.info(f"📊 Статус ответа авторизации: {login_response.status_code}")
            logger.info(f"📍 Финальный URL: {login_response.url}")
            
            # Если ошибка 400, возможно нужно использовать другой метод
            if login_response.status_code == 400:
                logger.warning("⚠️ Ошибка 400 при прямой авторизации")
                logger.warning("🔍 Проверяем, может быть уже авторизованы...")
                # Проверяем доступ к расписанию - возможно уже авторизованы
                test_response = self.session.get(f"{self.base_url}/schedule", timeout=10, allow_redirects=False)
                if test_response.status_code == 200:
                    self.is_authenticated = True
                    logger.info("✅ Уже авторизован! Ошибка 400 была из-за истекшей сессии, но доступ есть.")
                    return True
                
                # Если не авторизованы, возможно нужно обновить сессию
                logger.warning("⚠️ Попытка обновить сессию...")
                # Пробуем получить новую страницу авторизации (используем базовый OAuth URL)
                base_oauth_url = f"{self.id_url}/auth/realms/itmo/protocol/openid-connect/auth"
                new_auth_response = self.session.get(base_oauth_url, params={'client_id': 'student-personal-cabinet'}, timeout=10, allow_redirects=True)
                if new_auth_response.status_code == 200 and 'my.itmo.ru' in new_auth_response.url:
                    test_response = self.session.get(f"{self.base_url}/schedule", timeout=10)
                    if test_response.status_code == 200:
                        self.is_authenticated = True
                        logger.info("✅ Авторизация успешна после обновления сессии!")
                        return True
            
            if login_response.status_code in [200, 302, 303, 307, 308]:
                final_url = login_response.url
                
                # Проверяем, что мы попали на my.itmo.ru или получили редирект
                if 'my.itmo.ru' in final_url or 'schedule' in final_url.lower():
                    self.is_authenticated = True
                    logger.info("✅ Прямая авторизация через Keycloak успешна!")
                    return True
                
                # Если редирект на другую страницу, проверяем доступ к расписанию
                if login_response.history:
                    # Проверяем доступ к расписанию
                    test_response = self.session.get(f"{self.base_url}/schedule", timeout=10)
                    if test_response.status_code == 200:
                        self.is_authenticated = True
                        logger.info("✅ Авторизация успешна (проверено через доступ к расписанию)!")
                        return True
                
                # Если в ответе есть ошибка
                if 'error' in final_url.lower() or 'error' in login_response.text.lower()[:500]:
                    logger.error(f"❌ Ошибка в ответе авторизации: {login_response.text[:500]}")
                    return False
            
            logger.error(f"❌ Прямая авторизация не удалась. Статус: {login_response.status_code}, URL: {login_response.url}")
            if login_response.text:
                logger.error(f"Ответ сервера (первые 500 символов): {login_response.text[:500]}")
            return False
            
        except Exception as e:
            logger.error(f"❌ Ошибка прямой авторизации: {e}")
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
            
            # Пробуем получить через API (если есть)
            api_url = f"{self.base_url}/api/schedule"
            params = {'date': date_str}
            
            try:
                api_response = self.session.get(api_url, params=params, timeout=10)
                if api_response.status_code == 200:
                    try:
                        data = api_response.json()
                        if data:
                            logger.info("✅ Расписание получено через API")
                            return self._parse_api_schedule(data, target_date)
                    except:
                        pass
            except:
                pass
            
            # Если API не сработал, парсим HTML страницу
            schedule_url = f"{self.base_url}/schedule"
            params = {'date': date_str}
            logger.info(f"🌐 Запрос расписания: {schedule_url} с параметрами {params}")
            response = self.session.get(schedule_url, params=params, timeout=10)
            
            if response.status_code != 200:
                logger.error(f"❌ Ошибка получения расписания: {response.status_code}")
                logger.error(f"URL: {response.url}")
                # Проверяем, может быть нужна повторная авторизация
                if response.status_code in [401, 403] or 'login' in response.url.lower():
                    logger.warning("⚠️ Похоже, что сессия истекла. Пробуем повторную авторизацию...")
                    if self.authenticate():
                        # Повторяем запрос после авторизации
                        response = self.session.get(schedule_url, params=params, timeout=10)
                        if response.status_code != 200:
                            logger.error(f"❌ Ошибка получения расписания после повторной авторизации: {response.status_code}")
                            return None
                    else:
                        logger.error("❌ Не удалось повторно авторизоваться")
                        return None
                else:
                    return None
            
            # Проверяем кодировку ответа
            if response.encoding is None or response.encoding.lower() not in ['utf-8', 'utf8']:
                response.encoding = 'utf-8'
            
            # Логируем информацию о полученном ответе
            logger.info(f"✅ Получен ответ: {len(response.text)} символов, URL: {response.url}")
            
            # Проверяем, что мы не попали на страницу авторизации
            if 'login' in response.url.lower() or 'id.itmo.ru' in response.url:
                logger.warning("⚠️ Получена страница авторизации вместо расписания")
                logger.info("🔄 Выполняем повторную авторизацию...")
                
                # Сбрасываем флаг авторизации
                self.is_authenticated = False
                
                # Пробуем авторизоваться заново
                if self.authenticate():
                    logger.info("✅ Повторная авторизация успешна, повторяем запрос расписания...")
                    # Повторяем запрос расписания после авторизации
                    response = self.session.get(schedule_url, params=params, timeout=10)
                    
                    if response.status_code != 200:
                        logger.error(f"❌ Ошибка получения расписания после повторной авторизации: {response.status_code}")
                        return None
                    
                    # Проверяем кодировку ответа
                    if response.encoding is None or response.encoding.lower() not in ['utf-8', 'utf8']:
                        response.encoding = 'utf-8'
                    
                    # Проверяем снова, не попали ли на страницу авторизации
                    if 'login' in response.url.lower() or 'id.itmo.ru' in response.url:
                        logger.error("❌ После повторной авторизации все еще получаем страницу авторизации")
                        return None
                    
                    logger.info(f"✅ Получен ответ после повторной авторизации: {len(response.text)} символов, URL: {response.url}")
                else:
                    logger.error("❌ Не удалось выполнить повторную авторизацию")
                    return None
            
            # Логируем первые символы для отладки
            if not response.text or len(response.text) < 100:
                logger.warning(f"⚠️ Получен очень короткий ответ: {len(response.text)} символов")
                logger.warning(f"Первые 200 символов: {response.text[:200]}")
            
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
        
        logger.info(f"🔍 Начало парсинга HTML расписания (длина: {len(html)} символов)")
        
        # Ищем все элементы с классом "lesson" (структура из скриншота)
        lesson_elements = soup.find_all('div', class_=re.compile(r'lesson', re.I))
        logger.info(f"📚 Найдено элементов с классом 'lesson': {len(lesson_elements)}")
        
        for lesson_elem in lesson_elements:
            class_info = self._parse_lesson_element(lesson_elem)
            if class_info:
                schedule['classes'].append(class_info)
                logger.info(f"✅ Добавлено занятие: {class_info.get('subject', 'Unknown')}")
        
        # Если не нашли через класс lesson, пробуем альтернативные селекторы
        if not schedule['classes']:
            logger.warning("⚠️ Не найдено занятий через класс 'lesson', пробуем альтернативные методы...")
            
            # Ищем по структуре времени
            time_elements = soup.find_all('div', class_=re.compile(r'time', re.I))
            logger.info(f"⏰ Найдено элементов с классом 'time': {len(time_elements)}")
            
            for time_elem in time_elements:
                # Ищем родительский элемент с информацией о паре
                parent = time_elem.find_parent('div', class_=re.compile(r'lesson|schedule|calendar', re.I))
                if parent:
                    class_info = self._parse_lesson_element(parent)
                    if class_info:
                        schedule['classes'].append(class_info)
                        logger.info(f"✅ Добавлено занятие через time: {class_info.get('subject', 'Unknown')}")
            
            # Пробуем найти через data-атрибуты или другие селекторы
            if not schedule['classes']:
                # Ищем все элементы, которые могут содержать информацию о занятиях
                possible_selectors = [
                    ('div', {'data-testid': re.compile(r'lesson|class|schedule', re.I)}),
                    ('div', {'class': re.compile(r'schedule-item|class-item|event', re.I)}),
                    ('article', {}),
                    ('section', {'class': re.compile(r'schedule|calendar', re.I)}),
                ]
                
                for tag, attrs in possible_selectors:
                    elements = soup.find_all(tag, attrs)
                    logger.info(f"🔍 Найдено элементов {tag} с атрибутами {attrs}: {len(elements)}")
                    for elem in elements[:10]:  # Проверяем первые 10
                        class_info = self._parse_lesson_element(elem)
                        if class_info:
                            schedule['classes'].append(class_info)
                            logger.info(f"✅ Добавлено занятие через {tag}: {class_info.get('subject', 'Unknown')}")
        
        logger.info(f"📊 Итого найдено занятий: {len(schedule['classes'])}")
        
        # Если ничего не найдено, логируем структуру страницы для отладки
        if not schedule['classes']:
            logger.warning("⚠️ Занятия не найдены. Структура страницы:")
            # Ищем основные контейнеры
            main_containers = soup.find_all(['main', 'section', 'div'], class_=re.compile(r'main|content|schedule|calendar', re.I))
            logger.warning(f"   Найдено основных контейнеров: {len(main_containers)}")
            # Логируем первые 1000 символов HTML для анализа
            logger.warning(f"   Первые 1000 символов HTML: {html[:1000]}")
        
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
    
    def _parse_api_schedule(self, data: Dict, target_date: datetime) -> Dict:
        """
        Парсит расписание из JSON API ответа
        
        Args:
            data: JSON данные от API
            target_date: Дата расписания
            
        Returns:
            Словарь с расписанием в формате для бота
        """
        schedule = {
            'date': target_date,
            'classes': []
        }
        
        # Парсим структуру API (может отличаться, нужно адаптировать)
        if isinstance(data, list):
            for item in data:
                class_info = self._extract_class_info_from_api(item)
                if class_info:
                    schedule['classes'].append(class_info)
        elif isinstance(data, dict):
            # Пробуем разные возможные ключи
            for key in ['schedule', 'classes', 'lessons', 'items', 'data']:
                if key in data:
                    items = data[key] if isinstance(data[key], list) else [data[key]]
                    for item in items:
                        class_info = self._extract_class_info_from_api(item)
                        if class_info:
                            schedule['classes'].append(class_info)
                    break
        
        return schedule
    
    def _extract_class_info_from_api(self, item: Dict) -> Optional[Dict]:
        """
        Извлекает информацию о паре из JSON объекта API
        
        Args:
            item: JSON объект с данными о паре
            
        Returns:
            Словарь с информацией о паре или None
        """
        try:
            class_info = {}
            
            # Пробуем разные возможные ключи
            time_keys = ['time', 'start_time', 'time_start', 'begin_time', 'lesson_time', 'timeRange']
            subject_keys = ['subject', 'name', 'title', 'lesson_name', 'discipline', 'subjectName']
            room_keys = ['room', 'audience', 'auditorium', 'classroom', 'room_number', 'roomNumber']
            address_keys = ['address', 'location', 'building', 'address_name', 'buildingAddress']
            teacher_keys = ['teacher', 'instructor', 'lecturer', 'teacher_name', 'teacherName', 'educator']
            
            for key in time_keys:
                if key in item:
                    time_val = item[key]
                    if isinstance(time_val, dict):
                        # Если время в формате объекта
                        start = time_val.get('start') or time_val.get('begin')
                        end = time_val.get('end') or time_val.get('finish')
                        if start and end:
                            class_info['time'] = f"{start}-{end}"
                        elif start:
                            class_info['time'] = str(start)
                    else:
                        class_info['time'] = str(time_val)
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
                    teacher_val = item[key]
                    if isinstance(teacher_val, dict):
                        # Если преподаватель в формате объекта
                        name = teacher_val.get('name') or teacher_val.get('fullName')
                        if name:
                            class_info['teacher'] = str(name)
                    else:
                        class_info['teacher'] = str(teacher_val)
                    break
            
            if 'subject' in class_info or 'time' in class_info:
                class_info.setdefault('time', 'Время не указано')
                class_info.setdefault('subject', 'Предмет не указан')
                class_info.setdefault('room', 'Аудитория не указана')
                class_info.setdefault('address', 'Адрес не указан')
                return class_info
            
            return None
            
        except Exception as e:
            logger.error(f"Ошибка извлечения информации о паре из API: {e}")
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
