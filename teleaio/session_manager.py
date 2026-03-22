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
    UserPrivacyRestrictedError,
    AuthKeyUnregisteredError,
    PhoneNumberInvalidError
)
import config

logger = logging.getLogger(__name__)

class SessionManager:
    def __init__(self):
        self.api_id = config.TELEGRAM_API_ID
        self.api_hash = config.TELEGRAM_API_HASH
        self.pending_codes = {}
    
    async def create_session(self, user_id, phone, session_path):
        """Создает новую сессию, запрашивает код"""
        try:
            if os.path.exists(session_path):
                try:
                    os.remove(session_path)
                except:
                    pass
            
            client = TelegramClient(str(session_path), self.api_id, self.api_hash)
            await client.connect()
            
            if await client.is_user_authorized():
                await client.disconnect()
                return {"success": False, "error": "Аккаунт уже авторизован"}
            
            await client.send_code_request(phone)
            
            self.pending_codes[user_id] = {
                'client': client,
                'phone': phone,
                'session_path': str(session_path),
                'step': 'code',
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
        except PhoneNumberInvalidError:
            return {"success": False, "error": "Неверный номер телефона"}
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
        """Отправляет код подтверждения"""
        data = self.pending_codes.get(user_id)
        if not data:
            return {"success": False, "error": "Сессия не найдена. Запросите код заново."}
        
        client = data['client']
        phone = data['phone']
        
        try:
            code = code.strip().replace(' ', '').replace('-', '')
            await client.sign_in(phone, code)
            
            # Успешный вход (нет 2FA)
            del self.pending_codes[user_id]
            return {"success": True, "message": "Аккаунт успешно добавлен"}
            
        except SessionPasswordNeededError:
            # Требуется 2FA пароль
            logger.info(f"Пользователю {user_id} требуется 2FA пароль")
            self.pending_codes[user_id]['step'] = 'password'
            return {"success": False, "need_password": True, "message": "Требуется пароль 2FA"}
            
        except PhoneCodeInvalidError:
            return {"success": False, "error": "Неверный код"}
            
        except PhoneCodeExpiredError:
            return {"success": False, "error": "Код истек. Запросите новый код."}
            
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
            
            # Успешный вход с 2FA
            del self.pending_codes[user_id]
            return {"success": True, "message": "Аккаунт успешно добавлен"}
            
        except Exception as e:
            await client.disconnect()
            del self.pending_codes[user_id]
            logger.error(f"Ошибка проверки пароля: {e}")
            return {"success": False, "error": f"Неверный пароль 2FA: {str(e)}"}
    
    async def resend_code(self, user_id):
        """Запрашивает новый код"""
        data = self.pending_codes.get(user_id)
        if not data:
            return {"success": False, "error": "Сессия не найдена"}
        
        client = data['client']
        phone = data['phone']
        
        try:
            await client.send_code_request(phone)
            self.pending_codes[user_id]['created_at'] = asyncio.get_event_loop().time()
            return {"success": True, "message": "Новый код отправлен"}
            
        except FloodWaitError as e:
            return {"success": False, "error": f"Слишком много попыток. Подождите {e.seconds} сек"}
        except Exception as e:
            logger.error(f"Ошибка повторной отправки кода: {e}")
            return {"success": False, "error": str(e)}
    
    async def send_message(self, session_path, target, message):
        """Отправляет сообщение через сессию"""
        try:
            if not os.path.exists(session_path):
                logger.error(f"Файл сессии не найден: {session_path}")
                return {"success": False, "error": "Файл сессии не найден. Удалите аккаунт и добавьте заново."}
            
            client = TelegramClient(str(session_path), self.api_id, self.api_hash)
            await client.connect()
            
            if not await client.is_user_authorized():
                await client.disconnect()
                logger.error(f"Сессия не авторизована: {session_path}")
                return {"success": False, "error": "Сессия недействительна. Удалите аккаунт и добавьте заново."}
            
            try:
                if target.startswith('@'):
                    entity = target
                elif target.lstrip('-').isdigit():
                    entity = int(target)
                else:
                    entity = target
                
                try:
                    entity = await client.get_entity(entity)
                except ValueError:
                    pass
                except Exception as e:
                    await client.disconnect()
                    return {"success": False, "error": f"Ошибка получения получателя: {str(e)}"}
                
                await client.send_message(entity, message, parse_mode='html')
                await client.disconnect()
                return {"success": True}
                
            except FloodWaitError as e:
                await client.disconnect()
                return {"success": False, "error": f"flood_wait:{e.seconds}"}
            except ChatWriteForbiddenError:
                await client.disconnect()
                return {"success": False, "error": "Нет прав на отправку в этот чат"}
            except PeerFloodError:
                await client.disconnect()
                return {"success": False, "error": "Peer flood error - слишком много запросов"}
            except UserPrivacyRestrictedError:
                await client.disconnect()
                return {"success": False, "error": "Пользователь ограничил получение сообщений"}
            except AuthKeyUnregisteredError:
                await client.disconnect()
                return {"success": False, "error": "Сессия устарела. Удалите аккаунт и добавьте заново"}
            except Exception as e:
                await client.disconnect()
                logger.error(f"Ошибка отправки: {e}")
                return {"success": False, "error": str(e)}
                
        except Exception as e:
            logger.error(f"Критическая ошибка: {e}")
            return {"success": False, "error": str(e)}
    
    async def send_media(self, session_path, target, caption, file_id, file_type):
        if caption:
            return await self.send_message(session_path, target, caption)
        else:
            return await self.send_message(session_path, target, "📎 Медиа")
    
    def cancel_pending(self, user_id):
        if user_id in self.pending_codes:
            try:
                loop = asyncio.new_event_loop()
                loop.run_until_complete(self.pending_codes[user_id]['client'].disconnect())
                loop.close()
            except:
                pass
            del self.pending_codes[user_id]