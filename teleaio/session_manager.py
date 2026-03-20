import asyncio
import logging
import os
from pathlib import Path
from telethon import TelegramClient
from telethon.network.connection.tcpabridged import ConnectionTcpAbridged
from telethon.errors import (
    SessionPasswordNeededError, 
    PhoneCodeInvalidError, 
    FloodWaitError, 
    PhoneCodeExpiredError,
    ChatWriteForbiddenError,
    PeerFloodError,
    UserPrivacyRestrictedError,
    RPCError
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
        self._clients = {}
    
    async def _get_client(self, session_path, create_new=False):
        """Получает или создает клиент для сессии"""
        session_key = str(session_path)
        
        if create_new or session_key not in self._clients:
            try:
                client = TelegramClient(
                    str(session_path), 
                    self.api_id, 
                    self.api_hash,
                    connection=ConnectionTcpAbridged,
                    connection_retries=2,
                    retry_delay=1,
                    request_retries=3,
                    flood_sleep_threshold=60,
                    device_model="Telegram Bot",
                    system_version="4.16.30",
                    receive_updates=False,
                    timeout=10
                )
                
                await client.connect()
                
                if not await client.is_user_authorized():
                    await client.disconnect()
                    return None
                
                self._clients[session_key] = client
                logger.info(f"✅ Клиент создан для {session_path}")
            except Exception as e:
                logger.error(f"Ошибка создания клиента: {e}")
                return None
        
        return self._clients.get(session_key)
    
    async def create_session(self, user_id, phone, session_path):
        """Создает новую сессию"""
        try:
            if os.path.exists(session_path):
                try:
                    os.remove(session_path)
                except:
                    pass
            
            client = TelegramClient(
                str(session_path), 
                self.api_id, 
                self.api_hash,
                connection=ConnectionTcpAbridged,
                connection_retries=2,
                retry_delay=1,
                request_retries=3,
                flood_sleep_threshold=60,
                timeout=10
            )
            
            try:
                await asyncio.wait_for(client.connect(), timeout=15)
            except asyncio.TimeoutError:
                return {"success": False, "error": "Таймаут подключения. Проверьте интернет."}
            
            if await client.is_user_authorized():
                await client.disconnect()
                return {"success": False, "error": "Аккаунт уже авторизован"}
            
            try:
                result = await asyncio.wait_for(client.send_code_request(phone), timeout=15)
            except asyncio.TimeoutError:
                await client.disconnect()
                return {"success": False, "error": "Таймаут запроса кода. Проверьте интернет."}
            
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
        """Отправляет код подтверждения"""
        data = self.pending_codes.get(user_id)
        if not data:
            return {"success": False, "error": "Сессия не найдена. Запросите код заново."}
        
        client = data['client']
        phone = data['phone']
        
        try:
            code = code.strip().replace(' ', '').replace('-', '')
            
            try:
                await asyncio.wait_for(client.sign_in(phone, code), timeout=15)
            except asyncio.TimeoutError:
                return {"success": False, "error": "Таймаут проверки кода. Попробуйте еще раз."}
            
            session_key = str(data['session_path'])
            self._clients[session_key] = client
            del self.pending_codes[user_id]
            
            return {"success": True, "message": "Аккаунт успешно добавлен"}
            
        except SessionPasswordNeededError:
            self.pending_codes[user_id]['step'] = 'password'
            return {"success": True, "need_password": True}
            
        except PhoneCodeInvalidError:
            return {"success": False, "error": "Неверный код"}
            
        except PhoneCodeExpiredError:
            elapsed = asyncio.get_event_loop().time() - data.get('created_at', 0)
            if elapsed < 30:
                try:
                    await asyncio.wait_for(client.send_code_request(phone), timeout=15)
                    self.pending_codes[user_id]['created_at'] = asyncio.get_event_loop().time()
                    return {"success": False, "error": "Код не подошел. Попробуйте ввести еще раз.", "auto_resend": True}
                except Exception:
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
        """Запрашивает новый код"""
        data = self.pending_codes.get(user_id)
        if not data:
            return {"success": False, "error": "Сессия не найдена"}
        
        client = data['client']
        phone = data['phone']
        
        try:
            await asyncio.wait_for(client.send_code_request(phone), timeout=15)
            self.pending_codes[user_id]['created_at'] = asyncio.get_event_loop().time()
            return {"success": True, "message": "Новый код отправлен"}
            
        except FloodWaitError as e:
            return {"success": False, "error": f"Слишком много попыток. Подождите {e.seconds} сек"}
        except asyncio.TimeoutError:
            return {"success": False, "error": "Таймаут запроса. Проверьте интернет."}
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
            await asyncio.wait_for(client.sign_in(password=password), timeout=15)
            
            session_key = str(data['session_path'])
            self._clients[session_key] = client
            del self.pending_codes[user_id]
            
            return {"success": True, "message": "Аккаунт успешно добавлен"}
            
        except asyncio.TimeoutError:
            return {"success": False, "error": "Таймаут проверки пароля"}
        except Exception as e:
            await client.disconnect()
            if session_key in self._clients:
                del self._clients[session_key]
            del self.pending_codes[user_id]
            logger.error(f"Ошибка проверки пароля: {e}")
            return {"success": False, "error": str(e)}
    
    async def send_message(self, session_path, target, message):
        """Отправляет сообщение через сессию"""
        try:
            client = await self._get_client(session_path)
            if not client:
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
                except ValueError:
                    pass
                except Exception as e:
                    return {"success": False, "error": f"Получатель не найден: {target}"}
                
            except Exception as e:
                return {"success": False, "error": f"Ошибка получателя: {str(e)}"}
            
            try:
                await asyncio.wait_for(
                    client.send_message(entity, message, parse_mode='html', link_preview=False),
                    timeout=10
                )
                logger.info(f"✅ Отправлено в {target}")
                return {"success": True}
                
            except asyncio.TimeoutError:
                return {"success": False, "error": "Таймаут отправки"}
            except FloodWaitError as e:
                return {"success": False, "error": f"flood_wait:{e.seconds}"}
            except ChatWriteForbiddenError:
                return {"success": False, "error": "Нет прав на отправку"}
            except PeerFloodError:
                return {"success": False, "error": "Peer flood error"}
            except UserPrivacyRestrictedError:
                return {"success": False, "error": "Пользователь ограничил получение"}
            except Exception as e:
                logger.error(f"Ошибка отправки: {e}")
                return {"success": False, "error": str(e)}
            
        except Exception as e:
            logger.error(f"Критическая ошибка: {e}")
            return {"success": False, "error": str(e)}
    
    async def send_media(self, session_path, target, caption, file_id, file_type):
        """Отправляет медиа"""
        if caption:
            return await self.send_message(session_path, target, caption)
        else:
            return await self.send_message(session_path, target, "📎 Медиафайл")
    
    async def check_session(self, session_path):
        """Проверяет сессию"""
        try:
            client = TelegramClient(
                str(session_path), 
                self.api_id, 
                self.api_hash,
                connection=ConnectionTcpAbridged,
                timeout=5
            )
            try:
                await asyncio.wait_for(client.connect(), timeout=5)
            except:
                return False
            
            authorized = await client.is_user_authorized()
            await client.disconnect()
            return authorized
        except:
            return False
    
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
    
    async def cleanup_clients(self):
        """Очищает все клиенты"""
        for session_key, client in self._clients.items():
            try:
                await client.disconnect()
            except:
                pass
        self._clients.clear()