import asyncio
import logging
import os
import re
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
            
            del self.pending_codes[user_id]
            return {"success": True, "message": "Аккаунт успешно добавлен"}
            
        except SessionPasswordNeededError:
            logger.info(f"Пользователю {user_id} требуется 2FA пароль")
            self.pending_codes[user_id]['step'] = 'password'
            return {"success": False, "need_password": True}
            
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
        """Отправляет текстовое сообщение через сессию"""
        try:
            if not os.path.exists(session_path):
                logger.error(f"Файл сессии не найден: {session_path}")
                return {"success": False, "error": "Файл сессии не найден. Удалите аккаунт и добавьте заново."}
            
            # Преобразуем <blockquote> в стандартный формат цитаты
            message = message.replace('<blockquote>', '> ')
            message = message.replace('</blockquote>', '')
            
            client = TelegramClient(str(session_path), self.api_id, self.api_hash)
            
            try:
                await asyncio.wait_for(client.connect(), timeout=10)
            except asyncio.TimeoutError:
                return {"success": False, "error": "Таймаут подключения"}
            
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
    
    async def send_photo(self, session_path, target, caption, file_id, bot):
        """Отправляет фото через сессию, скачивая файл от бота"""
        try:
            if not os.path.exists(session_path):
                logger.error(f"Файл сессии не найден: {session_path}")
                return {"success": False, "error": "Файл сессии не найден"}
            
            # Преобразуем <blockquote> в стандартный формат цитаты
            if caption:
                caption = caption.replace('<blockquote>', '> ')
                caption = caption.replace('</blockquote>', '')
            
            # Скачиваем файл от бота
            safe_file_id = file_id.replace(':', '_').replace('/', '_')[-30:]
            download_path = config.DOWNLOADS_DIR / f"temp_{safe_file_id}.jpg"
            
            try:
                file = await bot.get_file(file_id)
                await bot.download_file(file.file_path, destination=download_path)
                logger.info(f"Фото скачано: {download_path}")
            except Exception as e:
                logger.error(f"Ошибка скачивания фото: {e}")
                if caption:
                    return await self.send_message(session_path, target, caption)
                return {"success": False, "error": "Не удалось загрузить фото"}
            
            client = TelegramClient(str(session_path), self.api_id, self.api_hash)
            
            try:
                await asyncio.wait_for(client.connect(), timeout=10)
            except asyncio.TimeoutError:
                try:
                    os.remove(download_path)
                except:
                    pass
                return {"success": False, "error": "Таймаут подключения"}
            
            if not await client.is_user_authorized():
                await client.disconnect()
                try:
                    os.remove(download_path)
                except:
                    pass
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
                    await client.disconnect()
                    try:
                        os.remove(download_path)
                    except:
                        pass
                    return {"success": False, "error": f"Ошибка получения получателя: {str(e)}"}
                
                # Отправляем фото
                await client.send_file(entity, str(download_path), caption=caption, parse_mode='html')
                await client.disconnect()
                
                # Удаляем временный файл
                try:
                    os.remove(download_path)
                except:
                    pass
                
                return {"success": True}
                
            except FloodWaitError as e:
                await client.disconnect()
                try:
                    os.remove(download_path)
                except:
                    pass
                return {"success": False, "error": f"flood_wait:{e.seconds}"}
            except Exception as e:
                await client.disconnect()
                try:
                    os.remove(download_path)
                except:
                    pass
                logger.error(f"Ошибка отправки фото: {e}")
                return {"success": False, "error": str(e)}
                
        except Exception as e:
            logger.error(f"Критическая ошибка: {e}")
            return {"success": False, "error": str(e)}
    
    def cancel_pending(self, user_id):
        if user_id in self.pending_codes:
            try:
                loop = asyncio.new_event_loop()
                loop.run_until_complete(self.pending_codes[user_id]['client'].disconnect())
                loop.close()
            except:
                pass
            del self.pending_codes[user_id]