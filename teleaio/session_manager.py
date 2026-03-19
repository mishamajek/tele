import asyncio
import logging
import os
from pathlib import Path
from telethon import TelegramClient
from telethon.errors import SessionPasswordNeededError, PhoneCodeInvalidError, FloodWaitError
import config

logger = logging.getLogger(__name__)

class SessionManager:
    """Класс для управления Telegram сессиями"""
    
    def __init__(self):
        self.api_id = config.TELEGRAM_API_ID
        self.api_hash = config.TELEGRAM_API_HASH
        self.active_clients = {}
        self.pending_codes = {}
    
    async def create_session(self, user_id, phone, session_path):
        """Создает новую сессию"""
        client = TelegramClient(str(session_path), self.api_id, self.api_hash)
        await client.connect()
        
        if await client.is_user_authorized():
            await client.disconnect()
            return {"success": False, "error": "Сессия уже авторизована"}
        
        try:
            await client.send_code_request(phone)
            self.pending_codes[user_id] = {
                'client': client,
                'phone': phone,
                'step': 'code'
            }
            return {"success": True, "need_code": True}
        except FloodWaitError as e:
            await client.disconnect()
            return {"success": False, "error": f"Подождите {e.seconds} сек"}
        except Exception as e:
            await client.disconnect()
            logger.error(f"Ошибка создания сессии: {e}")
            return {"success": False, "error": str(e)}
    
    async def submit_code(self, user_id, code):
        """Отправляет код подтверждения"""
        data = self.pending_codes.get(user_id)
        if not data:
            return {"success": False, "error": "Сессия не найдена"}
        
        client = data['client']
        phone = data['phone']
        
        try:
            await client.sign_in(phone, code)
            
            # Успешный вход
            await client.disconnect()
            del self.pending_codes[user_id]
            
            return {"success": True, "message": "Аккаунт добавлен"}
            
        except SessionPasswordNeededError:
            # Требуется 2FA
            self.pending_codes[user_id]['step'] = 'password'
            return {"success": True, "need_password": True}
            
        except PhoneCodeInvalidError:
            return {"success": False, "error": "Неверный код"}
            
        except Exception as e:
            await client.disconnect()
            del self.pending_codes[user_id]
            logger.error(f"Ошибка проверки кода: {e}")
            return {"success": False, "error": str(e)}
    
    async def submit_password(self, user_id, password):
        """Отправляет пароль 2FA"""
        data = self.pending_codes.get(user_id)
        if not data:
            return {"success": False, "error": "Сессия не найдена"}
        
        client = data['client']
        
        try:
            await client.sign_in(password=password)
            
            # Успешный вход
            await client.disconnect()
            del self.pending_codes[user_id]
            
            return {"success": True, "message": "Аккаунт добавлен"}
            
        except Exception as e:
            await client.disconnect()
            del self.pending_codes[user_id]
            logger.error(f"Ошибка проверки пароля: {e}")
            return {"success": False, "error": str(e)}
    
    async def send_message(self, session_path, target, message):
        """Отправляет сообщение через сессию"""
        try:
            client = TelegramClient(str(session_path), self.api_id, self.api_hash)
            await client.connect()
            
            if not await client.is_user_authorized():
                await client.disconnect()
                return {"success": False, "error": "Сессия недействительна"}
            
            # Получаем сущность получателя
            try:
                entity = await client.get_entity(target)
            except:
                # Если не получилось по username, пробуем по номеру
                try:
                    entity = await client.get_entity(int(target) if target.isdigit() else target)
                except:
                    await client.disconnect()
                    return {"success": False, "error": "Получатель не найден"}
            
            # Отправляем сообщение
            await client.send_message(entity, message)
            
            await client.disconnect()
            return {"success": True}
            
        except FloodWaitError as e:
            return {"success": False, "error": f"flood_wait:{e.seconds}"}
        except Exception as e:
            logger.error(f"Ошибка отправки сообщения: {e}")
            return {"success": False, "error": str(e)}
    
    async def check_session(self, session_path):
        """Проверяет, действительна ли сессия"""
        try:
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
        """Отменяет ожидающую сессию"""
        if user_id in self.pending_codes:
            try:
                loop = asyncio.new_event_loop()
                loop.run_until_complete(self.pending_codes[user_id]['client'].disconnect())
                loop.close()
            except:
                pass
            del self.pending_codes[user_id]