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
    def __init__(self):
        self.api_id = config.TELEGRAM_API_ID
        self.api_hash = config.TELEGRAM_API_HASH
        self.pending_codes = {}
    
    async def create_session(self, user_id, phone, session_path):
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
                'step': 'code'
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
        data = self.pending_codes.get(user_id)
        if not data:
            return {"success": False, "error": "Сессия не найдена. Запросите код заново."}
        
        client = data['client']
        phone = data['phone']
        
        try:
            code = code.strip().replace(' ', '').replace('-', '')
            await client.sign_in(phone, code)
            
            del self.pending_codes[user_id]
            return {"success": True, "message": "Аккаунт успешно добавлен"}
            
        except SessionPasswordNeededError:
            self.pending_codes[user_id]['step'] = 'password'
            return {"success": True, "need_password": True}
        except PhoneCodeInvalidError:
            return {"success": False, "error": "Неверный код"}
        except PhoneCodeExpiredError:
            return {"success": False, "error": "Код истек. Запросите новый код."}
        except Exception as e:
            await client.disconnect()
            del self.pending_codes[user_id]
            logger.error(f"Ошибка проверки кода: {e}")
            return {"success": False, "error": str(e)}
    
    async def resend_code(self, user_id):
        data = self.pending_codes.get(user_id)
        if not data:
            return {"success": False, "error": "Сессия не найдена"}
        
        client = data['client']
        phone = data['phone']
        
        try:
            await client.send_code_request(phone)
            return {"success": True, "message": "Новый код отправлен"}
        except FloodWaitError as e:
            return {"success": False, "error": f"Слишком много попыток. Подождите {e.seconds} сек"}
        except Exception as e:
            logger.error(f"Ошибка повторной отправки кода: {e}")
            return {"success": False, "error": str(e)}
    
    async def submit_password(self, user_id, password):
        data = self.pending_codes.get(user_id)
        if not data:
            return {"success": False, "error": "Сессия не найдена"}
        
        client = data['client']
        
        try:
            await client.sign_in(password=password)
            del self.pending_codes[user_id]
            return {"success": True, "message": "Аккаунт успешно добавлен"}
        except Exception as e:
            await client.disconnect()
            del self.pending_codes[user_id]
            logger.error(f"Ошибка проверки пароля: {e}")
            return {"success": False, "error": str(e)}
    
    async def send_message(self, session_path, target, message):
        try:
            client = TelegramClient(str(session_path), self.api_id, self.api_hash)
            await client.connect()
            
            if not await client.is_user_authorized():
                await client.disconnect()
                return {"success": False, "error": "Сессия недействительна"}
            
            try:
                if target.startswith('@'):
                    entity = target
                elif target.lstrip('-').isdigit():
                    entity = int(target)
                else:
                    entity = target
                
                try:
                    entity = await client.get_entity(entity)
                except:
                    pass
            except Exception as e:
                await client.disconnect()
                return {"success": False, "error": f"Получатель не найден: {target}"}
            
            try:
                await client.send_message(entity, message, parse_mode='html')
                await client.disconnect()
                return {"success": True}
            except FloodWaitError as e:
                await client.disconnect()
                return {"success": False, "error": f"flood_wait:{e.seconds}"}
            except Exception as e:
                await client.disconnect()
                return {"success": False, "error": str(e)}
                
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    async def send_media(self, session_path, target, caption, file_id, file_type):
        return await self.send_message(session_path, target, caption or "📎 Медиа")
    
    def cancel_pending(self, user_id):
        if user_id in self.pending_codes:
            try:
                loop = asyncio.new_event_loop()
                loop.run_until_complete(self.pending_codes[user_id]['client'].disconnect())
                loop.close()
            except:
                pass
            del self.pending_codes[user_id]