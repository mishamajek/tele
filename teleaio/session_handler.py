import asyncio
import logging
import os
import shutil
from pathlib import Path
from telethon import TelegramClient
from telethon.errors import SessionPasswordNeededError, PhoneCodeInvalidError, FloodWaitError
import config

logger = logging.getLogger(__name__)

class SessionHandler:
    """Класс для работы с Telegram сессиями"""
    
    def __init__(self):
        self.api_id = config.TELEGRAM_API_ID
        self.api_hash = config.TELEGRAM_API_HASH
        self.temp_sessions = {}
    
    async def request_code(self, phone_number):
        """Запрашивает код подтверждения для номера"""
        if not self.api_id or not self.api_hash:
            return {"success": False, "error": "API данные не настроены"}
        
        try:
            client = TelegramClient(f'temp_{phone_number}', self.api_id, self.api_hash)
            await client.connect()
            
            if await client.is_user_authorized():
                await client.disconnect()
                return {"success": False, "error": "Аккаунт уже авторизован"}
            
            await client.send_code_request(phone_number)
            
            # Сохраняем клиента для дальнейшего использования
            self.temp_sessions[phone_number] = client
            
            return {"success": True, "message": "Код отправлен"}
            
        except FloodWaitError as e:
            return {"success": False, "error": f"Слишком много попыток. Подождите {e.seconds} сек"}
        except Exception as e:
            logger.error(f"Ошибка запроса кода: {e}")
            return {"success": False, "error": str(e)}
    
    async def verify_code(self, phone_number, code):
        """Проверяет код и возвращает сообщение с кодом если есть"""
        client = self.temp_sessions.get(phone_number)
        if not client:
            return {"success": False, "error": "Сессия не найдена. Запросите код заново"}
        
        try:
            await client.sign_in(phone_number, code)
            
            # Если дошли сюда - авторизация успешна
            await client.disconnect()
            del self.temp_sessions[phone_number]
            
            return {"success": True, "message": "Аккаунт успешно авторизован"}
            
        except SessionPasswordNeededError:
            # Требуется 2FA
            return {"success": False, "need_password": True}
        except PhoneCodeInvalidError:
            return {"success": False, "error": "Неверный код"}
        except Exception as e:
            logger.error(f"Ошибка проверки кода: {e}")
            return {"success": False, "error": str(e)}
    
    async def verify_2fa(self, phone_number, password):
        """Проверяет 2FA пароль"""
        client = self.temp_sessions.get(phone_number)
        if not client:
            return {"success": False, "error": "Сессия не найдена"}
        
        try:
            await client.sign_in(password=password)
            await client.disconnect()
            del self.temp_sessions[phone_number]
            
            return {"success": True, "message": "Аккаунт успешно авторизован"}
            
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    async def get_code_from_session(self, session_path, target_phone):
        """
        Использует существующую сессию для получения кода подтверждения для другого номера
        Это основной метод для перехвата кодов
        """
        try:
            # Загружаем сессию продавца
            client = TelegramClient(str(session_path), self.api_id, self.api_hash)
            await client.connect()
            
            if not await client.is_user_authorized():
                await client.disconnect()
                return {"success": False, "error": "Сессия недействительна"}
            
            # Запрашиваем код для целевого номера
            await client.send_code_request(target_phone)
            
            # Ждем код (здесь нужно реализовать получение кода)
            # В реальном сценарии мы не можем "перехватить" код, так как он приходит в SMS
            # Поэтому пользователь должен ввести код вручную
            
            await client.disconnect()
            
            return {"success": True, "message": "Код запрошен. Введите код, который пришел в SMS"}
            
        except Exception as e:
            logger.error(f"Ошибка получения кода: {e}")
            return {"success": False, "error": str(e)}
    
    async def get_messages_from_session(self, session_path, limit=10):
        """Получает последние сообщения из сессии (для поиска кодов)"""
        try:
            client = TelegramClient(str(session_path), self.api_id, self.api_hash)
            await client.connect()
            
            if not await client.is_user_authorized():
                await client.disconnect()
                return {"success": False, "error": "Сессия недействительна"}
            
            messages = []
            async for msg in client.iter_messages('me', limit=limit):
                messages.append({
                    'id': msg.id,
                    'text': msg.text,
                    'date': msg.date.isoformat()
                })
            
            await client.disconnect()
            return {"success": True, "messages": messages}
            
        except Exception as e:
            logger.error(f"Ошибка получения сообщений: {e}")
            return {"success": False, "error": str(e)}
    
    def cleanup_temp(self, phone_number):
        """Очищает временные данные"""
        if phone_number in self.temp_sessions:
            try:
                loop = asyncio.new_event_loop()
                loop.run_until_complete(self.temp_sessions[phone_number].disconnect())
                loop.close()
            except:
                pass
            del self.temp_sessions[phone_number]