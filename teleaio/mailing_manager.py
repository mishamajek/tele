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
    def __init__(self, bot: Bot, db: Database):
        self.bot = bot
        self.db = db
        self.session_manager = SessionManager()
        self.active_mailings = {}
        self.running = True
        self.processing_tasks = {}
    
    def get_active_mailing(self, user_id):
        return self.db.get_active_mailing(user_id)
    
    def is_mailing_active(self, mailing_id):
        return mailing_id in self.active_mailings
    
    async def start_mailing(self, user_id, mailing_id, message_text, targets, media_file_id=None, media_type=None, interval=300):
        accounts = self.db.get_user_accounts(user_id)
        
        if not accounts:
            self.db.update_mailing_status(mailing_id, 'failed')
            return {"success": False, "error": "Нет активных аккаунтов"}
        
        account_targets = {}
        for i, target in enumerate(targets):
            account = accounts[i % len(accounts)]
            if account['id'] not in account_targets:
                account_targets[account['id']] = []
            account_targets[account['id']].append(target)
        
        for account_id, account_targets_list in account_targets.items():
            self.db.add_to_queue(mailing_id, account_id, account_targets_list)
        
        mailing = self.db.get_mailing(mailing_id)
        sent_count = mailing['messages_sent'] if mailing else 0
        
        self.active_mailings[mailing_id] = {
            'user_id': user_id,
            'message': message_text,
            'media_file_id': media_file_id,
            'media_type': media_type,
            'targets': targets,
            'accounts': accounts,
            'status': 'running',
            'interval': interval,
            'current_index': sent_count,
            'sent_count': sent_count
        }
        
        self.db.update_mailing_status(mailing_id, 'running')
        
        if mailing_id not in self.processing_tasks:
            task = asyncio.create_task(self._process_mailing_loop(mailing_id))
            self.processing_tasks[mailing_id] = task
        
        return {"success": True, "mailing_id": mailing_id}
    
    async def _process_mailing_loop(self, mailing_id):
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
                current_index = mailing.get('current_index', 0)
                sent_count = mailing.get('sent_count', 0)
                
                if not accounts:
                    logger.error(f"Нет аккаунтов для рассылки {mailing_id}")
                    break
                
                if not targets:
                    logger.error(f"Нет целей для рассылки {mailing_id}")
                    break
                
                target = targets[current_index % len(targets)]
                account = accounts[current_index % len(accounts)]
                
                max_per_day = int(self.db.get_setting('max_messages_per_day') or config.MAX_MESSAGES_PER_DAY)
                if account['messages_sent_today'] >= max_per_day:
                    logger.warning(f"Лимит для аккаунта {account['phone']}: {account['messages_sent_today']}/{max_per_day}")
                    mailing['current_index'] = current_index + 1
                    await asyncio.sleep(interval)
                    continue
                
                logger.info(f"📤 Отправка в {target} через {account['phone']}")
                
                try:
                    if media_file_id and media_type:
                        result = await self.session_manager.send_media(
                            account['session_path'],
                            target,
                            message,
                            media_file_id,
                            media_type
                        )
                    else:
                        result = await self.session_manager.send_message(
                            account['session_path'], 
                            target, 
                            message
                        )
                    
                    if result['success']:
                        sent_count += 1
                        mailing['sent_count'] = sent_count
                        mailing['current_index'] = current_index + 1
                        
                        self.db.update_account_last_used(account['id'])
                        self.db.update_mailing_status(mailing_id, 'running', sent_count)
                        logger.info(f"✅ Отправлено в {target} (всего: {sent_count})")
                        
                        pending = self.db.get_pending_messages(mailing_id, 100)
                        for item in pending:
                            if item['target'] == target:
                                self.db.update_queue_status(item['id'], 'sent')
                                break
                    else:
                        logger.error(f"❌ Ошибка отправки {target}: {result.get('error')}")
                        mailing['current_index'] = current_index + 1
                        
                        error_msg = result.get('error', '')
                        if 'flood_wait:' in error_msg:
                            try:
                                wait_time = int(error_msg.split(':')[1])
                                logger.warning(f"Flood wait {wait_time} сек")
                                await asyncio.sleep(wait_time)
                            except:
                                pass
                        
                except Exception as e:
                    logger.error(f"❌ Критическая ошибка отправки {target}: {e}")
                    mailing['current_index'] = current_index + 1
                
                await asyncio.sleep(interval)
                
        except Exception as e:
            logger.error(f"Ошибка в рассылке {mailing_id}: {e}")
            import traceback
            traceback.print_exc()
        finally:
            if mailing_id in self.active_mailings:
                self.db.update_mailing_status(mailing_id, 'stopped')
                del self.active_mailings[mailing_id]
            if mailing_id in self.processing_tasks:
                del self.processing_tasks[mailing_id]
            logger.info(f"Рассылка {mailing_id} остановлена")
    
    async def stop_mailing(self, mailing_id):
        if mailing_id in self.active_mailings:
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
            logger.info(f"Интервал рассылки {mailing_id} обновлен на {interval} сек")
        return True
    
    def shutdown(self):
        self.running = False
        for task in self.processing_tasks.values():
            task.cancel()
        self.processing_tasks.clear()
        self.active_mailings.clear()