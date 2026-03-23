import asyncio
import logging
import sqlite3
import json
from aiogram import Bot
from database import Database
from session_manager import SessionManager
import config

logger = logging.getLogger(__name__)

class MailingManager:
    def __init__(self, bot: Bot, db: Database):
        self.bot = bot
        self.db = db
        self.session_manager = SessionManager()
        self.active_mailings = {}
        self.paused_mailings = {}
        self.running = True
        self.processing_tasks = {}
        self._sending_semaphore = asyncio.Semaphore(10)  # Ограничиваем параллельные отправки
    
    def get_active_mailing(self, user_id):
        for mailing_id, data in self.active_mailings.items():
            if data['user_id'] == user_id:
                return self.db.get_mailing(mailing_id)
        return None
    
    def is_mailing_active(self, mailing_id):
        return mailing_id in self.active_mailings
    
    async def start_mailing(self, user_id, mailing_id, message_text, targets, media_file_id=None, media_type=None, interval=300):
        accounts = self.db.get_user_accounts(user_id)
        if not accounts:
            self.db.update_mailing_status(mailing_id, 'failed')
            return {"success": False, "error": "Нет активных аккаунтов"}
        
        mailing_info = self.db.get_mailing(mailing_id)
        name = mailing_info.get('name', 'Без названия') if mailing_info else 'Без названия'
        
        # Очередь создаётся только при первом запуске
        pending = self.db.get_pending_messages(mailing_id, 1)
        if not pending:
            account_targets = {}
            for i, target in enumerate(targets):
                account = accounts[i % len(accounts)]
                if account['id'] not in account_targets:
                    account_targets[account['id']] = []
                account_targets[account['id']].append(target)
            for account_id, targets_list in account_targets.items():
                self.db.add_to_queue(mailing_id, account_id, targets_list)
        
        mailing = self.db.get_mailing(mailing_id)
        sent_count = mailing['messages_sent'] if mailing else 0
        
        self.active_mailings[mailing_id] = {
            'user_id': user_id,
            'name': name,
            'message': message_text,
            'media_file_id': media_file_id,
            'media_type': media_type,
            'targets': targets,
            'accounts': accounts,
            'interval': interval,
            'sent_count': sent_count,
            'running_tasks': set()
        }
        
        self.db.update_mailing_status(mailing_id, 'running')
        if mailing_id in self.paused_mailings:
            del self.paused_mailings[mailing_id]
        
        if mailing_id not in self.processing_tasks:
            task = asyncio.create_task(self._process_mailing_parallel(mailing_id))
            self.processing_tasks[mailing_id] = task
            logger.info(f"✅ Запущена параллельная рассылка {mailing_id} - '{name}'")
        
        return {"success": True, "mailing_id": mailing_id}
    
    async def resume_mailing(self, mailing_id):
        if mailing_id in self.paused_mailings:
            data = self.paused_mailings[mailing_id]
            self.active_mailings[mailing_id] = data
            del self.paused_mailings[mailing_id]
            self.db.update_mailing_status(mailing_id, 'running')
            if mailing_id not in self.processing_tasks:
                task = asyncio.create_task(self._process_mailing_parallel(mailing_id))
                self.processing_tasks[mailing_id] = task
            logger.info(f"▶️ Рассылка {mailing_id} возобновлена")
            return {"success": True}
        return {"success": False, "error": "Рассылка не найдена в паузе"}
    
    async def _process_mailing_parallel(self, mailing_id):
        try:
            while self.running and mailing_id in self.active_mailings:
                mailing = self.active_mailings.get(mailing_id)
                if not mailing:
                    break
                
                accounts = mailing['accounts']
                targets = mailing['targets']
                message = mailing.get('message')
                media_file_id = mailing.get('media_file_id')
                media_type = mailing.get('media_type')
                interval = mailing.get('interval', 300)
                name = mailing.get('name', 'Без названия')
                
                if not accounts or not targets:
                    break
                
                logger.info(f"🚀 Параллельная отправка {len(targets)} сообщений (рассылка: {name})")
                
                # Создаём задачи для всех получателей
                tasks = []
                for i, target in enumerate(targets):
                    account = accounts[i % len(accounts)]
                    tasks.append(self._send_to_target(mailing_id, target, account, message, media_file_id, media_type))
                
                # Ждём завершения всех отправок с ограничением параллельности
                results = await asyncio.gather(*tasks, return_exceptions=True)
                
                sent_count = sum(1 for r in results if r and r.get('success'))
                failed_count = sum(1 for r in results if r and not r.get('success'))
                
                if mailing_id in self.active_mailings:
                    mailing['sent_count'] = mailing.get('sent_count', 0) + sent_count
                    self.db.update_mailing_status(mailing_id, 'running', mailing['sent_count'])
                
                logger.info(f"✅ Параллельная отправка завершена: +{sent_count} успешно, {failed_count} ошибок")
                await asyncio.sleep(interval)
                
        except Exception as e:
            logger.error(f"Ошибка в рассылке {mailing_id}: {e}")
        finally:
            if mailing_id in self.active_mailings:
                data = self.active_mailings[mailing_id]
                self.paused_mailings[mailing_id] = data
                del self.active_mailings[mailing_id]
                self.db.update_mailing_status(mailing_id, 'stopped')
                logger.info(f"⏸ Рассылка {mailing_id} приостановлена")
            if mailing_id in self.processing_tasks:
                del self.processing_tasks[mailing_id]
    
    async def _send_to_target(self, mailing_id, target, account, message, media_file_id, media_type):
        async with self._sending_semaphore:
            try:
                max_per_day = int(self.db.get_setting('max_messages_per_day') or config.MAX_MESSAGES_PER_DAY)
                if account['messages_sent_today'] >= max_per_day:
                    return {"success": False, "error": "Лимит на сегодня"}
                
                if media_file_id and media_type == 'photo':
                    result = await self.session_manager.send_photo(
                        account['session_path'], target, message, media_file_id, self.bot
                    )
                else:
                    result = await self.session_manager.send_message(
                        account['session_path'], target, message
                    )
                
                if result['success']:
                    # Асинхронное обновление БД
                    await self.db.update_account_last_used_async(account['id'])
                    return {"success": True}
                else:
                    return {"success": False, "error": result.get('error')}
            except Exception as e:
                logger.error(f"Ошибка отправки {target}: {e}")
                return {"success": False, "error": str(e)}
    
    async def stop_mailing(self, mailing_id):
        if mailing_id in self.active_mailings:
            self.paused_mailings[mailing_id] = self.active_mailings[mailing_id]
            del self.active_mailings[mailing_id]
            self.db.update_mailing_status(mailing_id, 'stopped')
            return True
        mailing = self.db.get_mailing(mailing_id)
        if mailing and mailing['status'] == 'running':
            self.db.update_mailing_status(mailing_id, 'stopped')
            return True
        return False
    
    async def update_interval(self, mailing_id, interval):
        if mailing_id in self.active_mailings:
            self.active_mailings[mailing_id]['interval'] = interval
        elif mailing_id in self.paused_mailings:
            self.paused_mailings[mailing_id]['interval'] = interval
        return True
    
    def shutdown(self):
        self.running = False
        for task in self.processing_tasks.values():
            task.cancel()
        self.processing_tasks.clear()
        self.active_mailings.clear()
        self.paused_mailings.clear()