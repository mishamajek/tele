import asyncio
import logging
from datetime import datetime
import random
from typing import List, Dict
import json

from database import Database
from session_manager import SessionManager
import config

logger = logging.getLogger(__name__)

class MailingManager:
    """Класс для управления массовыми рассылками"""
    
    def __init__(self):
        self.db = Database()
        self.session_manager = SessionManager()
        self.active_mailings = {}
        self.running = True
    
    async def start_mailing(self, user_id, message_text, targets):
        """Запускает новую рассылку"""
        # Получаем активные аккаунты пользователя
        accounts = self.db.get_user_accounts(user_id)
        if not accounts:
            return {"success": False, "error": "Нет активных аккаунтов"}
        
        # Создаем запись о рассылке
        mailing_id = self.db.create_mailing(user_id, message_text, targets)
        
        # Добавляем сообщения в очередь
        self.db.add_to_queue(mailing_id, accounts[0]['id'], targets)
        
        # Запускаем обработку
        self.active_mailings[mailing_id] = {
            'user_id': user_id,
            'message': message_text,
            'targets': targets,
            'accounts': accounts,
            'status': 'running'
        }
        
        # Запускаем фоновую задачу
        asyncio.create_task(self._process_mailing(mailing_id))
        
        return {"success": True, "mailing_id": mailing_id}
    
    async def _process_mailing(self, mailing_id):
        """Обрабатывает рассылку в фоне"""
        self.db.update_mailing_status(mailing_id, 'running')
        
        mailing = self.active_mailings.get(mailing_id)
        if not mailing:
            return
        
        accounts = mailing['accounts']
        targets = mailing['targets']
        message = mailing['message']
        
        # Получаем настройки
        max_per_day = int(self.db.get_setting('max_messages_per_day') or config.MAX_MESSAGES_PER_DAY)
        delay = int(self.db.get_setting('message_delay') or config.MESSAGE_DELAY)
        
        sent_count = 0
        failed_count = 0
        
        # Распределяем цели по аккаунтам
        account_targets = {}
        for i, target in enumerate(targets):
            account = accounts[i % len(accounts)]
            if account['id'] not in account_targets:
                account_targets[account['id']] = []
            account_targets[account['id']].append(target)
        
        # Отправляем сообщения
        for account_id, account_targets_list in account_targets.items():
            account = next((a for a in accounts if a['id'] == account_id), None)
            if not account:
                continue
            
            session_path = account['session_path']
            
            for target in account_targets_list:
                if not self.running:
                    break
                
                # Проверяем лимиты
                if account['messages_sent_today'] >= max_per_day:
                    logger.warning(f"Аккаунт {account['phone']} достиг лимита на сегодня")
                    continue
                
                # Отправляем сообщение
                result = await self.session_manager.send_message(session_path, target, message)
                
                # Находим соответствующую запись в очереди
                queue_items = self.db.get_pending_messages(1000)
                queue_id = None
                for item in queue_items:
                    if item['target'] == target and item['account_id'] == account_id:
                        queue_id = item['id']
                        break
                
                if result['success']:
                    sent_count += 1
                    self.db.update_account_last_used(account_id)
                    if queue_id:
                        self.db.update_queue_status(queue_id, 'sent')
                    logger.info(f"✅ Отправлено {target}")
                else:
                    failed_count += 1
                    if queue_id:
                        self.db.update_queue_status(queue_id, 'failed', result.get('error'))
                    
                    # Обработка flood wait
                    if result.get('error', '').startswith('flood_wait:'):
                        wait_time = int(result['error'].split(':')[1])
                        logger.warning(f"Flood wait {wait_time} сек")
                        await asyncio.sleep(wait_time)
                
                # Обновляем статистику рассылки
                self.db.update_mailing_status(mailing_id, 'running', sent_count)
                
                # Задержка между сообщениями
                await asyncio.sleep(delay)
        
        # Завершаем рассылку
        self.db.update_mailing_status(mailing_id, 'completed', sent_count)
        
        if mailing_id in self.active_mailings:
            del self.active_mailings[mailing_id]
    
    async def stop_mailing(self, mailing_id):
        """Останавливает рассылку"""
        if mailing_id in self.active_mailings:
            self.active_mailings[mailing_id]['status'] = 'stopped'
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