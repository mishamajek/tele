import asyncio
import logging
from datetime import datetime
import json

from aiogram import Bot
from aiogram.enums import ParseMode

from database import Database
from session_manager import SessionManager
import config

logger = logging.getLogger(__name__)

class MailingManager:
    """Класс для управления массовыми рассылками"""
    
    def __init__(self, bot: Bot, db: Database):
        self.bot = bot
        self.db = db
        self.session_manager = SessionManager()
        self.active_mailings = {}
        self.running = True
        self.processing_tasks = {}
    
    async def start_mailing(self, user_id, mailing_id, message_text, targets, media_file_id=None, media_type=None):
        """Запускает новую рассылку"""
        # Получаем активные аккаунты пользователя
        accounts = self.db.get_user_accounts(user_id)
        if not accounts:
            self.db.update_mailing_status(mailing_id, 'failed')
            return {"success": False, "error": "Нет активных аккаунтов"}
        
        # Добавляем сообщения в очередь
        # Распределяем цели по аккаунтам
        account_targets = {}
        for i, target in enumerate(targets):
            account = accounts[i % len(accounts)]
            if account['id'] not in account_targets:
                account_targets[account['id']] = []
            account_targets[account['id']].append(target)
        
        # Добавляем в очередь для каждого аккаунта
        for account_id, account_targets_list in account_targets.items():
            self.db.add_to_queue(mailing_id, account_id, account_targets_list)
        
        # Запускаем обработку
        self.active_mailings[mailing_id] = {
            'user_id': user_id,
            'message': message_text,
            'media_file_id': media_file_id,
            'media_type': media_type,
            'targets': targets,
            'accounts': accounts,
            'status': 'running'
        }
        
        # Запускаем фоновую задачу, если еще не запущена
        if mailing_id not in self.processing_tasks:
            task = asyncio.create_task(self._process_mailing(mailing_id))
            self.processing_tasks[mailing_id] = task
        
        return {"success": True, "mailing_id": mailing_id}
    
    async def _process_mailing(self, mailing_id):
        """Обрабатывает рассылку в фоне"""
        try:
            self.db.update_mailing_status(mailing_id, 'running')
            
            mailing = self.active_mailings.get(mailing_id)
            if not mailing:
                mailing = self._load_mailing_from_db(mailing_id)
                if not mailing:
                    return
                self.active_mailings[mailing_id] = mailing
            
            accounts = mailing['accounts']
            message = mailing.get('message')
            media_file_id = mailing.get('media_file_id')
            media_type = mailing.get('media_type')
            
            # Получаем настройки
            max_per_day = int(self.db.get_setting('max_messages_per_day') or config.MAX_MESSAGES_PER_DAY)
            delay = int(self.db.get_setting('message_delay') or config.MESSAGE_DELAY)
            
            sent_count = 0
            failed_count = 0
            
            # Получаем все ожидающие сообщения для этой рассылки
            pending = self.db.get_pending_messages(mailing_id, 100)
            
            # Создаем словарь аккаунтов для быстрого доступа
            accounts_dict = {acc['id']: acc for acc in accounts}
            
            for item in pending:
                if not self.running or mailing_id not in self.active_mailings:
                    break
                
                account = accounts_dict.get(item['account_id'])
                if not account:
                    self.db.update_queue_status(item['id'], 'failed', 'Аккаунт не найден')
                    failed_count += 1
                    continue
                
                # Проверяем лимиты
                if account['messages_sent_today'] >= max_per_day:
                    self.db.update_queue_status(item['id'], 'failed', 'Лимит на сегодня')
                    failed_count += 1
                    continue
                
                # Отправляем сообщение
                if media_file_id and media_type:
                    result = await self.session_manager.send_media(
                        account['session_path'],
                        item['target'],
                        message,
                        media_file_id,
                        media_type
                    )
                else:
                    result = await self.session_manager.send_message(
                        account['session_path'], 
                        item['target'], 
                        message
                    )
                
                if result['success']:
                    sent_count += 1
                    self.db.update_account_last_used(account['id'])
                    self.db.update_queue_status(item['id'], 'sent')
                    self.db.update_mailing_status(mailing_id, 'running', sent_count)
                    logger.info(f"✅ Отправлено {item['target']}")
                else:
                    failed_count += 1
                    self.db.update_queue_status(item['id'], 'failed', result.get('error'))
                    
                    # Обработка flood wait
                    if result.get('error', '').startswith('flood_wait:'):
                        wait_time = int(result['error'].split(':')[1])
                        logger.warning(f"Flood wait {wait_time} сек")
                        await asyncio.sleep(wait_time)
                
                # Задержка между сообщениями
                await asyncio.sleep(delay)
            
            # Проверяем, остались ли неотправленные
            remaining = self.db.get_pending_messages(mailing_id, 1)
            if not remaining:
                # Завершаем рассылку
                self.db.update_mailing_status(mailing_id, 'completed', sent_count)
                logger.info(f"✅ Рассылка {mailing_id} завершена")
            else:
                self.db.update_mailing_status(mailing_id, 'stopped', sent_count)
                logger.info(f"⏸ Рассылка {mailing_id} приостановлена")
            
        except Exception as e:
            logger.error(f"Ошибка в рассылке {mailing_id}: {e}")
        finally:
            if mailing_id in self.active_mailings:
                del self.active_mailings[mailing_id]
            if mailing_id in self.processing_tasks:
                del self.processing_tasks[mailing_id]
    
    def _load_mailing_from_db(self, mailing_id):
        """Загружает данные рассылки из БД"""
        mailing = self.db.get_mailing(mailing_id)
        if not mailing:
            return None
        
        accounts = self.db.get_user_accounts(mailing['user_id'])
        targets = json.loads(mailing['targets'])
        
        return {
            'user_id': mailing['user_id'],
            'message': mailing['message_text'],
            'media_file_id': mailing['media_file_id'],
            'media_type': mailing['media_type'],
            'targets': targets,
            'accounts': accounts,
            'status': mailing['status']
        }
    
    async def stop_mailing(self, mailing_id):
        """Останавливает рассылку"""
        if mailing_id in self.active_mailings:
            del self.active_mailings[mailing_id]
            self.db.update_mailing_status(mailing_id, 'stopped')
            return True
        
        # Проверяем в БД
        mailing = self.db.get_mailing(mailing_id)
        if mailing and mailing['status'] == 'running':
            self.db.update_mailing_status(mailing_id, 'stopped')
            return True
        
        return False
    
    def get_mailing_status(self, mailing_id):
        """Получает статус рассылки"""
        mailing = self.db.get_mailing(mailing_id)
        if not mailing:
            return None
        
        stats = self.db.get_queue_stats(mailing_id)
        
        return {
            'id': mailing['id'],
            'status': mailing['status'],
            'total': stats['total'],
            'sent': stats['sent'],
            'failed': stats['failed'],
            'started': mailing['started'],
            'completed': mailing['completed']
        }
    
    def shutdown(self):
        """Останавливает все рассылки"""
        self.running = False
        for task in self.processing_tasks.values():
            task.cancel()
        self.processing_tasks.clear()
        self.active_mailings.clear()