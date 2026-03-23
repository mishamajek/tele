import asyncio
import logging
import random
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
        self.paused_mailings = {}
        self.running = True
        self.processing_tasks = {}
        self._send_semaphore = asyncio.Semaphore(10)

    def get_active_mailing(self, user_id):
        for mailing_id, data in self.active_mailings.items():
            if data['user_id'] == user_id:
                return data
        return None

    def is_mailing_active(self, mailing_id):
        return mailing_id in self.active_mailings

    async def start_mailing(self, user_id, mailing_id, message_text, targets, media_file_id=None, media_type=None, interval=300):
        accounts = await self.db.get_user_accounts(user_id)

        if not accounts:
            await self.db.update_mailing_status(mailing_id, 'failed')
            return {"success": False, "error": "Нет активных аккаунтов"}

        mailing_info = await self.db.get_mailing(mailing_id)
        name = mailing_info.get('name', 'Без названия') if mailing_info else 'Без названия'
        sent_count = mailing_info.get('messages_sent', 0) if mailing_info else 0

        self.active_mailings[mailing_id] = {
            'user_id': user_id,
            'name': name,
            'message': message_text,
            'media_file_id': media_file_id,
            'media_type': media_type,
            'targets': targets,
            'accounts': accounts,
            'status': 'running',
            'interval': interval,
            'sent_count': sent_count,
            'total_targets': len(targets)
        }

        await self.db.update_mailing_status(mailing_id, 'running')

        if mailing_id in self.paused_mailings:
            del self.paused_mailings[mailing_id]

        if mailing_id not in self.processing_tasks:
            task = asyncio.create_task(self._process_mailing_loop(mailing_id))
            self.processing_tasks[mailing_id] = task
            logger.info(f"✅ Запущена бесконечная рассылка {mailing_id} - '{name}'")

        return {"success": True, "mailing_id": mailing_id}

    async def _process_mailing_loop(self, mailing_id):
        """Бесконечный цикл рассылки"""
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
                sent_count = mailing.get('sent_count', 0)

                if not accounts:
                    logger.error(f"Нет аккаунтов для рассылки {mailing_id}")
                    break

                if not targets:
                    logger.error(f"Нет целей для рассылки {mailing_id}")
                    break

                # Проверяем лимиты
                max_per_day = int(await self.db.get_setting('max_messages_per_day') or config.MAX_MESSAGES_PER_DAY)
                accounts_ok = [acc for acc in accounts if acc['messages_sent_today'] < max_per_day]
                if not accounts_ok:
                    logger.warning(f"Все аккаунты превысили лимит, ожидание {interval} сек")
                    await asyncio.sleep(interval)
                    continue

                # Отправляем всем получателям параллельно
                tasks = []
                for i, target in enumerate(targets):
                    account = accounts_ok[i % len(accounts_ok)]
                    tasks.append(self._send_to_target(mailing_id, target, account, message, media_file_id, media_type))

                results = await asyncio.gather(*tasks, return_exceptions=True)

                # Подсчитываем успешные отправки и собираем аккаунты для обновления
                sent_in_cycle = 0
                accounts_to_update = {}
                for r in results:
                    if r and r.get('success'):
                        sent_in_cycle += 1
                        acc = r.get('account')
                        if acc:
                            accounts_to_update[acc['id']] = accounts_to_update.get(acc['id'], 0) + 1

                # ОДНОКРАТНО обновляем статистику для всех аккаунтов
                for account_id, count in accounts_to_update.items():
                    for _ in range(count):
                        await self.db.update_account_last_used(account_id)

                new_sent_count = sent_count + sent_in_cycle
                mailing['sent_count'] = new_sent_count
                await self.db.update_mailing_status(mailing_id, 'running', new_sent_count)

                logger.info(f"✅ Цикл рассылки {name}: +{sent_in_cycle} успешно. Всего: {new_sent_count}")

                await asyncio.sleep(interval)

        except asyncio.CancelledError:
            logger.info(f"Рассылка {mailing_id} отменена")
        except Exception as e:
            logger.error(f"Ошибка в рассылке {mailing_id}: {e}")
            import traceback
            traceback.print_exc()
        finally:
            if mailing_id in self.active_mailings:
                data = self.active_mailings[mailing_id]
                self.paused_mailings[mailing_id] = data
                del self.active_mailings[mailing_id]
                await self.db.update_mailing_status(mailing_id, 'stopped')
                logger.info(f"⏸ Рассылка {mailing_id} приостановлена")
            if mailing_id in self.processing_tasks:
                del self.processing_tasks[mailing_id]

    async def _send_to_target(self, mailing_id, target, account, message, media_file_id, media_type):
        """Отправляет сообщение одному получателю — БЕЗ ЗАПИСИ В БД"""
        try:
            max_per_day = int(await self.db.get_setting('max_messages_per_day') or config.MAX_MESSAGES_PER_DAY)
            if account['messages_sent_today'] >= max_per_day:
                logger.warning(f"Лимит для аккаунта {account['phone']}: {account['messages_sent_today']}/{max_per_day}")
                return {"success": False, "error": "Лимит на сегодня", "account": account}

            logger.info(f"📤 Отправка в {target} через {account['phone']}")

            if media_file_id and media_type == 'photo':
                result = await self.session_manager.send_photo(
                    account['session_path'],
                    target,
                    message,
                    media_file_id,
                    self.bot
                )
            else:
                result = await self.session_manager.send_message(
                    account['session_path'],
                    target,
                    message
                )

            if result['success']:
                logger.info(f"✅ Отправлено в {target}")
                return {"success": True, "account": account}
            else:
                logger.error(f"❌ Ошибка отправки {target}: {result.get('error')}")
                return {"success": False, "error": result.get('error'), "account": account}

        except Exception as e:
            logger.error(f"❌ Критическая ошибка отправки {target}: {e}")
            return {"success": False, "error": str(e), "account": account}

    async def resume_mailing(self, mailing_id):
        if mailing_id in self.paused_mailings:
            data = self.paused_mailings[mailing_id]
            if not data.get('accounts') or not data.get('targets'):
                return {"success": False, "error": "Нет аккаунтов или целей"}
            self.active_mailings[mailing_id] = data
            del self.paused_mailings[mailing_id]

            await self.db.update_mailing_status(mailing_id, 'running')

            if mailing_id not in self.processing_tasks:
                task = asyncio.create_task(self._process_mailing_loop(mailing_id))
                self.processing_tasks[mailing_id] = task

            logger.info(f"▶️ Рассылка {mailing_id} возобновлена")
            return {"success": True}

        return {"success": False, "error": "Рассылка не найдена в паузе"}

    async def stop_mailing(self, mailing_id):
        if mailing_id in self.active_mailings:
            self.paused_mailings[mailing_id] = self.active_mailings[mailing_id]
            del self.active_mailings[mailing_id]
            await self.db.update_mailing_status(mailing_id, 'stopped')
            logger.info(f"⏸ Рассылка {mailing_id} остановлена (на паузе)")
            return True

        mailing = await self.db.get_mailing(mailing_id)
        if mailing and mailing['status'] == 'running':
            await self.db.update_mailing_status(mailing_id, 'stopped')
            return True

        return False

    async def update_interval(self, mailing_id, interval):
        if mailing_id in self.active_mailings:
            self.active_mailings[mailing_id]['interval'] = interval
            logger.info(f"Интервал рассылки {mailing_id} обновлен на {interval} сек")
        elif mailing_id in self.paused_mailings:
            self.paused_mailings[mailing_id]['interval'] = interval
            logger.info(f"Интервал рассылки {mailing_id} (на паузе) обновлен на {interval} сек")
        return True

    def shutdown(self):
        self.running = False
        for task in self.processing_tasks.values():
            task.cancel()
        self.processing_tasks.clear()
        self.active_mailings.clear()
        self.paused_mailings.clear()