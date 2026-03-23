import sqlite3
import time
import asyncio
from contextlib import contextmanager
from typing import List, Dict, Optional, Tuple
from datetime import datetime, timedelta
import json
from config import (
    DEFAULT_SUBSCRIPTION_PRICE,
    DEFAULT_TRIAL_HOURS,
    MAX_MESSAGES_PER_DAY,
    MESSAGE_DELAY
)

class Database:
    def __init__(self, db_path='database.db'):
        self.db_path = db_path
        self.init_db()
    
    @contextmanager
    def get_conn(self, retry=3, delay=0.1):
        for attempt in range(retry):
            try:
                conn = sqlite3.connect(self.db_path, timeout=30)
                conn.row_factory = sqlite3.Row
                conn.execute("PRAGMA journal_mode=WAL")
                conn.execute("PRAGMA synchronous=NORMAL")
                try:
                    yield conn
                finally:
                    conn.close()
                return
            except sqlite3.OperationalError as e:
                if "database is locked" in str(e) and attempt < retry - 1:
                    time.sleep(delay * (attempt + 1))
                    continue
                raise
    
    def init_db(self):
        with self.get_conn() as conn:
            c = conn.cursor()
            c.execute("PRAGMA journal_mode=WAL")
            c.execute("PRAGMA synchronous=NORMAL")
            
            c.execute('''CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                telegram_id INTEGER UNIQUE,
                username TEXT,
                first_name TEXT,
                joined_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                subscription_end TIMESTAMP,
                trial_used BOOLEAN DEFAULT 0,
                daily_messages_sent INTEGER DEFAULT 0,
                last_message_date TEXT
            )''')
            
            c.execute('''CREATE TABLE IF NOT EXISTS user_accounts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                phone TEXT NOT NULL,
                session_path TEXT NOT NULL,
                is_active BOOLEAN DEFAULT 1,
                added_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_used TIMESTAMP,
                messages_sent_today INTEGER DEFAULT 0,
                total_messages_sent INTEGER DEFAULT 0,
                FOREIGN KEY (user_id) REFERENCES users(telegram_id)
            )''')
            
            c.execute('''CREATE TABLE IF NOT EXISTS mailings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                name TEXT DEFAULT 'Без названия',
                message_text TEXT,
                targets TEXT NOT NULL,
                media_file_id TEXT,
                media_type TEXT,
                interval INTEGER DEFAULT 300,
                accounts_used INTEGER DEFAULT 0,
                messages_sent INTEGER DEFAULT 0,
                total_targets INTEGER DEFAULT 0,
                status TEXT DEFAULT 'pending',
                started TIMESTAMP,
                completed TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(telegram_id)
            )''')
            
            c.execute("PRAGMA table_info(mailings)")
            columns = [col[1] for col in c.fetchall()]
            if 'name' not in columns:
                c.execute('ALTER TABLE mailings ADD COLUMN name TEXT DEFAULT "Без названия"')
            if 'media_file_id' not in columns:
                c.execute('ALTER TABLE mailings ADD COLUMN media_file_id TEXT')
            if 'media_type' not in columns:
                c.execute('ALTER TABLE mailings ADD COLUMN media_type TEXT')
            if 'total_targets' not in columns:
                c.execute('ALTER TABLE mailings ADD COLUMN total_targets INTEGER DEFAULT 0')
            if 'interval' not in columns:
                c.execute('ALTER TABLE mailings ADD COLUMN interval INTEGER DEFAULT 300')
            
            c.execute('''CREATE TABLE IF NOT EXISTS purchases (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                item_type TEXT NOT NULL,
                amount INTEGER NOT NULL,
                purchase_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(telegram_id)
            )''')
            
            c.execute('''CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )''')
            
            c.execute('''CREATE TABLE IF NOT EXISTS message_queue (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                mailing_id INTEGER NOT NULL,
                account_id INTEGER NOT NULL,
                target TEXT NOT NULL,
                status TEXT DEFAULT 'pending',
                sent_date TIMESTAMP,
                error TEXT,
                FOREIGN KEY (mailing_id) REFERENCES mailings(id),
                FOREIGN KEY (account_id) REFERENCES user_accounts(id)
            )''')
            
            c.execute('CREATE INDEX IF NOT EXISTS idx_message_queue_status ON message_queue(status)')
            c.execute('CREATE INDEX IF NOT EXISTS idx_message_queue_mailing_id ON message_queue(mailing_id)')
            c.execute('CREATE INDEX IF NOT EXISTS idx_mailings_user_id ON mailings(user_id)')
            c.execute('CREATE INDEX IF NOT EXISTS idx_mailings_status ON mailings(status)')
            c.execute('CREATE INDEX IF NOT EXISTS idx_user_accounts_user_id ON user_accounts(user_id)')
            
            default_settings = [
                ('subscription_price', str(DEFAULT_SUBSCRIPTION_PRICE)),
                ('trial_hours', str(DEFAULT_TRIAL_HOURS)),
                ('max_messages_per_day', str(MAX_MESSAGES_PER_DAY)),
                ('message_delay', str(MESSAGE_DELAY))
            ]
            for key, value in default_settings:
                c.execute('INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)', (key, value))
            
            conn.commit()
    
    # === АСИНХРОННЫЕ МЕТОДЫ ===
    
    async def get_user(self, telegram_id):
        with self.get_conn() as conn:
            c = conn.cursor()
            c.execute('SELECT * FROM users WHERE telegram_id = ?', (telegram_id,))
            row = c.fetchone()
            return dict(row) if row else None
    
    async def create_user(self, telegram_id, username=None, first_name=None):
        try:
            with self.get_conn() as conn:
                c = conn.cursor()
                c.execute('INSERT INTO users (telegram_id, username, first_name) VALUES (?, ?, ?)', (telegram_id, username, first_name))
                conn.commit()
            return True
        except:
            return False
    
    async def get_all_users(self):
        with self.get_conn() as conn:
            c = conn.cursor()
            c.execute('SELECT telegram_id FROM users')
            return [row['telegram_id'] for row in c.fetchall()]
    
    async def reset_daily_messages(self):
        with self.get_conn() as conn:
            c = conn.cursor()
            c.execute('UPDATE users SET daily_messages_sent = 0 WHERE last_message_date < ?', (datetime.now().strftime('%Y-%m-%d'),))
            conn.commit()
    
    async def reset_accounts_daily_messages(self):
        with self.get_conn() as conn:
            c = conn.cursor()
            c.execute('UPDATE user_accounts SET messages_sent_today = 0')
            conn.commit()
    
    async def has_active_subscription(self, telegram_id):
        user = await self.get_user(telegram_id)
        if not user or not user['subscription_end']:
            return False
        try:
            end_date = datetime.fromisoformat(user['subscription_end'])
            return end_date > datetime.now()
        except:
            return False
    
    async def get_subscription_end(self, telegram_id):
        user = await self.get_user(telegram_id)
        return user['subscription_end'] if user else None
    
    async def activate_subscription(self, telegram_id, days=7):
        end_date = (datetime.now() + timedelta(days=days)).isoformat()
        with self.get_conn() as conn:
            c = conn.cursor()
            c.execute('UPDATE users SET subscription_end = ? WHERE telegram_id = ?', (end_date, telegram_id))
            conn.commit()
        return True
    
    async def activate_trial(self, telegram_id):
        user = await self.get_user(telegram_id)
        if user and user['trial_used']:
            return False
        end_date = (datetime.now() + timedelta(hours=24)).isoformat()
        with self.get_conn() as conn:
            c = conn.cursor()
            c.execute('UPDATE users SET subscription_end = ?, trial_used = 1 WHERE telegram_id = ?', (end_date, telegram_id))
            conn.commit()
        return True
    
    async def check_trial_available(self, telegram_id):
        user = await self.get_user(telegram_id)
        return user and not user['trial_used']
    
    async def add_user_account(self, user_id, phone, session_path):
        try:
            with self.get_conn() as conn:
                c = conn.cursor()
                c.execute('INSERT INTO user_accounts (user_id, phone, session_path) VALUES (?, ?, ?)', (user_id, phone, session_path))
                conn.commit()
            return True
        except:
            return False
    
    async def get_user_accounts(self, user_id):
        with self.get_conn() as conn:
            c = conn.cursor()
            c.execute('SELECT * FROM user_accounts WHERE user_id = ? AND is_active = 1 ORDER BY added_date DESC', (user_id,))
            return [dict(row) for row in c.fetchall()]
    
    async def get_user_account(self, account_id):
        with self.get_conn() as conn:
            c = conn.cursor()
            c.execute('SELECT * FROM user_accounts WHERE id = ?', (account_id,))
            row = c.fetchone()
            return dict(row) if row else None
    
    async def update_account_last_used(self, account_id):
        # Метод оставлен, но не используется в рассылке
        with self.get_conn() as conn:
            c = conn.cursor()
            c.execute('UPDATE user_accounts SET last_used = CURRENT_TIMESTAMP, messages_sent_today = messages_sent_today + 1, total_messages_sent = total_messages_sent + 1 WHERE id = ?', (account_id,))
            conn.commit()
    
    async def deactivate_account(self, account_id):
        with self.get_conn() as conn:
            c = conn.cursor()
            c.execute('UPDATE user_accounts SET is_active = 0 WHERE id = ?', (account_id,))
            conn.commit()
    
    async def deactivate_all_accounts(self, user_id):
        with self.get_conn() as conn:
            c = conn.cursor()
            c.execute('UPDATE user_accounts SET is_active = 0 WHERE user_id = ?', (user_id,))
            conn.commit()
    
    async def delete_user_account(self, account_id, user_id):
        with self.get_conn() as conn:
            c = conn.cursor()
            c.execute('DELETE FROM user_accounts WHERE id = ? AND user_id = ?', (account_id, user_id))
            conn.commit()
        return True
    
    async def create_mailing(self, user_id, name, message_text, targets, media_file_id=None, media_type=None, interval=300):
        with self.get_conn() as conn:
            c = conn.cursor()
            c.execute('''INSERT INTO mailings (user_id, name, message_text, targets, media_file_id, media_type, total_targets, interval) VALUES (?, ?, ?, ?, ?, ?, ?, ?)''', (user_id, name, message_text, json.dumps(targets), media_file_id, media_type, len(targets), interval))
            conn.commit()
            return c.lastrowid
    
    async def get_mailing(self, mailing_id):
        with self.get_conn() as conn:
            c = conn.cursor()
            c.execute('SELECT * FROM mailings WHERE id = ?', (mailing_id,))
            row = c.fetchone()
            return dict(row) if row else None
    
    async def update_mailing_status(self, mailing_id, status, messages_sent=None):
        with self.get_conn() as conn:
            c = conn.cursor()
            if status == 'running' and messages_sent is None:
                c.execute('UPDATE mailings SET status = ?, started = CURRENT_TIMESTAMP WHERE id = ?', (status, mailing_id))
            elif status in ('completed', 'stopped'):
                c.execute('UPDATE mailings SET status = ?, completed = CURRENT_TIMESTAMP WHERE id = ?', (status, mailing_id))
            elif messages_sent is not None:
                c.execute('UPDATE mailings SET messages_sent = ? WHERE id = ?', (messages_sent, mailing_id))
            else:
                c.execute('UPDATE mailings SET status = ? WHERE id = ?', (status, mailing_id))
            conn.commit()
    
    async def get_user_mailings(self, user_id, limit=10):
        with self.get_conn() as conn:
            c = conn.cursor()
            c.execute('SELECT * FROM mailings WHERE user_id = ? ORDER BY started DESC LIMIT ?', (user_id, limit))
            return [dict(row) for row in c.fetchall()]
    
    async def delete_mailing(self, mailing_id):
        with self.get_conn() as conn:
            c = conn.cursor()
            c.execute('DELETE FROM message_queue WHERE mailing_id = ?', (mailing_id,))
            c.execute('DELETE FROM mailings WHERE id = ?', (mailing_id,))
            conn.commit()
        return True
    
    async def get_active_mailing(self, user_id):
        with self.get_conn() as conn:
            c = conn.cursor()
            c.execute('SELECT * FROM mailings WHERE user_id = ? AND status = "running" ORDER BY started DESC LIMIT 1', (user_id,))
            row = c.fetchone()
            return dict(row) if row else None
    
    async def update_mailing_interval(self, mailing_id, interval):
        with self.get_conn() as conn:
            c = conn.cursor()
            c.execute('UPDATE mailings SET interval = ? WHERE id = ?', (interval, mailing_id))
            conn.commit()
    
    async def update_mailing_name(self, mailing_id, name):
        with self.get_conn() as conn:
            c = conn.cursor()
            c.execute('UPDATE mailings SET name = ? WHERE id = ?', (name, mailing_id))
            conn.commit()
        return True
    
    async def add_to_queue(self, mailing_id, account_id, target):
        with self.get_conn() as conn:
            c = conn.cursor()
            c.execute('INSERT INTO message_queue (mailing_id, account_id, target) VALUES (?, ?, ?)', (mailing_id, account_id, target))
            conn.commit()
    
    async def clear_queue(self, mailing_id):
        with self.get_conn() as conn:
            c = conn.cursor()
            c.execute('DELETE FROM message_queue WHERE mailing_id = ?', (mailing_id,))
            conn.commit()
    
    async def get_pending_messages(self, mailing_id=None, limit=10):
        with self.get_conn() as conn:
            c = conn.cursor()
            if mailing_id:
                c.execute('SELECT * FROM message_queue WHERE status = "pending" AND mailing_id = ? ORDER BY id LIMIT ?', (mailing_id, limit))
            else:
                c.execute('SELECT * FROM message_queue WHERE status = "pending" ORDER BY id LIMIT ?', (limit,))
            return [dict(row) for row in c.fetchall()]
    
    async def update_queue_status(self, queue_id, status, error=None):
        with self.get_conn() as conn:
            c = conn.cursor()
            if error:
                c.execute('UPDATE message_queue SET status = ?, error = ?, sent_date = CURRENT_TIMESTAMP WHERE id = ?', (status, error, queue_id))
            else:
                c.execute('UPDATE message_queue SET status = ?, sent_date = CURRENT_TIMESTAMP WHERE id = ?', (status, queue_id))
            conn.commit()
    
    async def get_queue_stats(self, mailing_id):
        with self.get_conn() as conn:
            c = conn.cursor()
            c.execute('SELECT COUNT(*) as total, SUM(CASE WHEN status = "sent" THEN 1 ELSE 0 END) as sent, SUM(CASE WHEN status = "failed" THEN 1 ELSE 0 END) as failed FROM message_queue WHERE mailing_id = ?', (mailing_id,))
            row = c.fetchone()
            return {'total': row['total'], 'sent': row['sent'] or 0, 'failed': row['failed'] or 0}
    
    async def add_purchase(self, user_id, item_type, amount):
        with self.get_conn() as conn:
            c = conn.cursor()
            c.execute('INSERT INTO purchases (user_id, item_type, amount) VALUES (?, ?, ?)', (user_id, item_type, amount))
            conn.commit()
        return True
    
    async def get_user_purchases(self, user_id):
        with self.get_conn() as conn:
            c = conn.cursor()
            c.execute('SELECT * FROM purchases WHERE user_id = ? ORDER BY purchase_date DESC', (user_id,))
            return [dict(row) for row in c.fetchall()]
    
    async def get_setting(self, key):
        with self.get_conn() as conn:
            c = conn.cursor()
            c.execute('SELECT value FROM settings WHERE key = ?', (key,))
            row = c.fetchone()
            return row['value'] if row else None
    
    async def update_setting(self, key, value):
        with self.get_conn() as conn:
            c = conn.cursor()
            c.execute('UPDATE settings SET value = ? WHERE key = ?', (value, key))
            conn.commit()
        return True
    
    async def get_all_settings(self):
        with self.get_conn() as conn:
            c = conn.cursor()
            c.execute('SELECT * FROM settings')
            return {row['key']: row['value'] for row in c.fetchall()}
    
    async def get_stats(self):
        with self.get_conn() as conn:
            c = conn.cursor()
            users = c.execute('SELECT COUNT(*) FROM users').fetchone()[0]
            active_subs = c.execute('SELECT COUNT(*) FROM users WHERE subscription_end > CURRENT_TIMESTAMP').fetchone()[0]
            user_accounts = c.execute('SELECT COUNT(*) FROM user_accounts').fetchone()[0]
            mailings = c.execute('SELECT COUNT(*) FROM mailings').fetchone()[0]
            messages_sent = c.execute('SELECT COUNT(*) FROM message_queue WHERE status = "sent"').fetchone()[0]
            purchases_total = c.execute('SELECT SUM(amount) FROM purchases').fetchone()[0] or 0
            return {
                'users': users,
                'active_subs': active_subs,
                'user_accounts': user_accounts,
                'mailings': mailings,
                'messages_sent': messages_sent,
                'purchases_total': purchases_total
            }