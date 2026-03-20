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
    
    async def start_mailing(self, user_id, mailing_id, message_text, targets, media_file_id=None, media_type=None):
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
        
        self.active_mailings[mailing_id] = {
            'user_id': user_id,
            'message': message_text,
            'media_file_id': media_file_id,
            'media_type': media_type,
            'targets': targets,
            'accounts': accounts,
            'status': 'running'
        }
        
        if mailing_id not in self.processing_tasks:
            task = asyncio.create_task(self._process_mailing(mailing_id))
            self.processing_tasks[mailing_id] = task
        
        return {"success": True, "mailing_id": mailing_id}
    
    async def _process_mailing(self, mailing_id):
        try:
            self.db.update_mailing_status(mailing_id, 'running')
            
            mailing = self.active_mailings.get(mailing_id)
            if not mailing:
                mailing = self._load_mailing_from_db(mailing_id)
                if not mailing:
                    return
                self.active_mailings[mailing_id] = mailing
            
            accounts = mailing['accounts']
            if not accounts:
                self.db.update_mailing_status(mailing_id, 'failed')
                return
            
            message = mailing.get('message')
            media_file_id = mailing.get('media_file_id')
            media_type = mailing.get('media_type')
            
            max_per_day = int(self.db.get_setting('max_messages_per_day') or config.MAX_MESSAGES_PER_DAY)
            delay = int(self.db.get_setting('message_delay') or config.MESSAGE_DELAY)
            
            sent_count = 0
            failed_count = 0
            
            pending = self.db.get_pending_messages(mailing_id, 100)
            
            if not pending:
                self.db.update_mailing_status(mailing_id, 'completed', 0)
                return
            
            accounts_dict = {acc['id']: acc for acc in accounts}
            
            for item in pending:
                if not self.running or mailing_id not in self.active_mailings:
                    break
                
                account = accounts_dict.get(item['account_id'])
                if not account:
                    self.db.update_queue_status(item['id'], 'failed', 'Аккаунт не найден')
                    failed_count += 1
                    continue
                
                if account['messages_sent_today'] >= max_per_day:
                    self.db.update_queue_status(item['id'], 'failed', 'Лимит на сегодня')
                    failed_count += 1
                    continue
                
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
                else:
                    failed_count += 1
                    self.db.update_queue_status(item['id'], 'failed', result.get('error'))
                    
                    if result.get('error', '').startswith('flood_wait:'):
                        wait_time = int(result['error'].split(':')[1])
                        await asyncio.sleep(wait_time)
                
                await asyncio.sleep(delay)
            
            remaining = self.db.get_pending_messages(mailing_id, 1)
            if not remaining:
                self.db.update_mailing_status(mailing_id, 'completed', sent_count)
            else:
                self.db.update_mailing_status(mailing_id, 'stopped', sent_count)
            
        except Exception as e:
            logger.error(f"Ошибка в рассылке {mailing_id}: {e}")
        finally:
            if mailing_id in self.active_mailings:
                del self.active_mailings[mailing_id]
            if mailing_id in self.processing_tasks:
                del self.processing_tasks[mailing_id]
    
    def _load_mailing_from_db(self, mailing_id):
        mailing = self.db.get_mailing(mailing_id)
        if not mailing:
            return None
        
        accounts = self.db.get_user_accounts(mailing['user_id'])
        targets = json.loads(mailing['targets'])
        
        return {
            'user_id': mailing['user_id'],
            'message': mailing['message_text'],
            'media_file_id': mailing.get('media_file_id'),
            'media_type': mailing.get('media_type'),
            'targets': targets,
            'accounts': accounts,
            'status': mailing['status']
        }
    
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
    
    def shutdown(self):
        self.running = False
        for task in self.processing_tasks.values():
            task.cancel()
        self.processing_tasks.clear()
        self.active_mailings.clear()