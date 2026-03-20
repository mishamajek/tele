import asyncio
import logging
import os
from pathlib import Path
from telethon import TelegramClient
from telethon.errors import (
    SessionPasswordNeededError, 
    PhoneCodeInvalidError, 
    FloodWaitError, 
    PhoneCodeExpiredError,
    ChatWriteForbiddenError,
    PeerFloodError,
    UserPrivacyRestrictedError
)
import config

logger = logging.getLogger(__name__)

class SessionManager:
    """Класс для управления Telegram сессиями"""
    
    def __init__(self):
        self.api_id = config.TELEGRAM_API_ID
        self.api_hash = config.TELEGRAM_API_HASH
        self.active_clients = {}
        self.pending_codes = {}
        self._clients = {}  # Кэш клиентов для быстрой отправки
    
    async def _get_client(self, session_path):
        """Получает или создает клиент для сессии"""
        session_key = str(session_path)
        
        if session_key not in self._clients:
            client = TelegramClient(str(session_path), self.api_id, self.api_hash)
            await client.connect()
            
            if not await client.is_user_authorized():
                await client.disconnect()
                return None
            
            self._clients[session_key] = client
        
        return self._clients[session_key]
    
    async def create_session(self, user_id, phone, session_path):
        """Создает новую сессию и сохраняет клиента для дальнейшего использования"""
        try:
            # Создаем клиента
            client = TelegramClient(str(session_path), self.api_id, self.api_hash)
            await client.connect()
            
            # Проверяем, не авторизован ли уже
            if await client.is_user_authorized():
                await client.disconnect()
                return {"success": False, "error": "Сессия уже авторизована"}
            
            # Запрашиваем код
            result = await client.send_code_request(phone)
            
            # Сохраняем клиента в pending_codes
            self.pending_codes[user_id] = {
                'client': client,
                'phone': phone,
                'session_path': str(session_path),
                'step': 'code',
                'phone_code_hash': getattr(result, 'phone_code_hash', None),
                'created_at': asyncio.get_event_loop().time()
            }
            
            return {"success": True, "need_code": True}
            
        except FloodWaitError as e:
            if user_id in self.pending_codes:
                try:
                    await self.pending_codes[user_id]['client'].disconnect()
                except:
                    pass
                del self.pending_codes[user_id]
            return {"success": False, "error": f"Слишком много попыток. Подождите {e.seconds} сек"}
            
        except Exception as e:
            if user_id in self.pending_codes:
                try:
                    await self.pending_codes[user_id]['client'].disconnect()
                except:
                    pass
                del self.pending_codes[user_id]
            logger.error(f"Ошибка создания сессии: {e}")
            return {"success": False, "error": str(e)}
    
    async def submit_code(self, user_id, code):
        """Отправляет код подтверждения, используя тот же клиент"""
        data = self.pending_codes.get(user_id)
        if not data:
            return {"success": False, "error": "Сессия не найдена. Запросите код заново."}
        
        client = data['client']
        phone = data['phone']
        
        try:
            # Очищаем код от лишних символов
            code = code.strip().replace(' ', '').replace('-', '')
            
            # Пытаемся войти с кодом
            await client.sign_in(phone, code)
            
            # Успешный вход - сохраняем клиент в кэш
            session_key = str(data['session_path'])
            self._clients[session_key] = client
            del self.pending_codes[user_id]
            
            return {"success": True, "message": "Аккаунт успешно добавлен"}
            
        except SessionPasswordNeededError:
            # Требуется 2FA
            self.pending_codes[user_id]['step'] = 'password'
            return {"success": True, "need_password": True}
            
        except PhoneCodeInvalidError:
            return {"success": False, "error": "Неверный код"}
            
        except PhoneCodeExpiredError:
            elapsed = asyncio.get_event_loop().time() - data.get('created_at', 0)
            
            if elapsed < 30:
                try:
                    await client.send_code_request(phone)
                    self.pending_codes[user_id]['created_at'] = asyncio.get_event_loop().time()
                    return {"success": False, "error": "Код не подошел. Попробуйте ввести еще раз.", "auto_resend": True}
                except Exception as e:
                    pass
            
            return {"success": False, "error": "Код истек. Запросите новый код."}
            
        except Exception as e:
            await client.disconnect()
            if session_key in self._clients:
                del self._clients[session_key]
            del self.pending_codes[user_id]
            logger.error(f"Ошибка проверки кода: {e}")
            return {"success": False, "error": str(e)}
    
    async def resend_code(self, user_id):
        """Запрашивает новый код подтверждения"""
        data = self.pending_codes.get(user_id)
        if not data:
            return {"success": False, "error": "Сессия не найдена"}
        
        client = data['client']
        phone = data['phone']
        
        try:
            await client.send_code_request(phone)
            self.pending_codes[user_id]['created_at'] = asyncio.get_event_loop().time()
            self.pending_codes[user_id]['step'] = 'code'
            return {"success": True, "message": "Новый код отправлен"}
            
        except FloodWaitError as e:
            return {"success": False, "error": f"Слишком много попыток. Подождите {e.seconds} сек"}
        except Exception as e:
            logger.error(f"Ошибка повторной отправки кода: {e}")
            return {"success": False, "error": str(e)}
    
    async def submit_password(self, user_id, password):
        """Отправляет пароль 2FA"""
        data = self.pending_codes.get(user_id)
        if not data:
            return {"success": False, "error": "Сессия не найдена"}
        
        client = data['client']
        
        try:
            await client.sign_in(password=password)
            
            # Успешный вход - сохраняем клиент в кэш
            session_key = str(data['session_path'])
            self._clients[session_key] = client
            del self.pending_codes[user_id]
            
            return {"success": True, "message": "Аккаунт успешно добавлен"}
            
        except Exception as e:
            await client.disconnect()
            if session_key in self._clients:
                del self._clients[session_key]
            del self.pending_codes[user_id]
            logger.error(f"Ошибка проверки пароля: {e}")
            return {"success": False, "error": str(e)}
    
    async def send_message(self, session_path, target, message):
        """Отправляет сообщение через сессию - исправленная версия"""
        try:
            # Получаем клиент
            client = await self._get_client(session_path)
            if not client:
                return {"success": False, "error": "Сессия недействительна"}
            
            # Определяем получателя
            try:
                # Пробуем получить как username или номер
                if target.startswith('@'):
                    # Это username
                    entity = await client.get_entity(target)
                elif target.lstrip('-').isdigit():
                    # Это ID (может быть с минусом)
                    entity = int(target)
                else:
                    # Пробуем как номер телефона
                    entity = await client.get_entity(target)
            except ValueError:
                # Если не получилось, пробуем как есть
                entity = target
            except Exception as e:
                logger.error(f"Ошибка получения сущности {target}: {e}")
                return {"success": False, "error": f"Получатель не найден: {target}"}
            
            # Отправляем сообщение
            try:
                await client.send_message(entity, message, parse_mode='html')
                logger.info(f"✅ Отправлено в {target}")
                return {"success": True}
            except FloodWaitError as e:
                logger.warning(f"Flood wait {e.seconds} сек для {target}")
                return {"success": False, "error": f"flood_wait:{e.seconds}"}
            except ChatWriteForbiddenError:
                return {"success": False, "error": "Нет прав на отправку в этот чат"}
            except PeerFloodError:
                return {"success": False, "error": "Peer flood error"}
            except UserPrivacyRestrictedError:
                return {"success": False, "error": "Пользователь ограничил получение сообщений"}
            except Exception as e:
                logger.error(f"Ошибка отправки в {target}: {e}")
                return {"success": False, "error": str(e)}
            
        except Exception as e:
            logger.error(f"Критическая ошибка отправки: {e}")
            return {"success": False, "error": str(e)}
    
    async def send_media(self, session_path, target, caption, file_id, file_type):
        """Отправляет медиа через сессию"""
        # Для отправки медиа через Telethon нужно скачать файл
        # Пока отправляем только текст, если есть
        if caption:
            return await self.send_message(session_path, target, caption)
        else:
            # Отправляем сообщение-заглушку
            return await self.send_message(session_path, target, "📎 Медиафайл")
    
    async def check_session(self, session_path):
        """Проверяет, действительна ли сессия"""
        try:
            session_key = str(session_path)
            if session_key in self._clients:
                client = self._clients[session_key]
                if await client.is_user_authorized():
                    return True
            
            client = TelegramClient(str(session_path), self.api_id, self.api_hash)
            await client.connect()
            authorized = await client.is_user_authorized()
            await client.disconnect()
            return authorized
        except:
            return False
    
    async def get_session_info(self, session_path):
        """Получает информацию о сессии (номер телефона)"""
        try:
            client = TelegramClient(str(session_path), self.api_id, self.api_hash)
            await client.connect()
            
            if not await client.is_user_authorized():
                await client.disconnect()
                return None
            
            me = await client.get_me()
            await client.disconnect()
            
            return {
                'phone': me.phone,
                'username': me.username,
                'first_name': me.first_name
            }
        except:
            return None
    
    def cancel_pending(self, user_id):
        """Отменяет ожидающую сессию и освобождает ресурсы"""
        if user_id in self.pending_codes:
            try:
                loop = asyncio.new_event_loop()
                loop.run_until_complete(self.pending_codes[user_id]['client'].disconnect())
                loop.close()
            except:
                pass
            del self.pending_codes[user_id]
    
    async def cleanup_clients(self):
        """Очищает все клиенты (вызывать при остановке)"""
        for session_key, client in self._clients.items():
            try:
                await client.disconnect()
            except:
                pass
        self._clients.clear()