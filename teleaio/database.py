import sqlite3
from typing import List, Dict, Optional, Tuple
from contextlib import contextmanager
from datetime import datetime, timedelta
import json

class Database:
    def __init__(self, db_path='database.db'):
        self.db_path = db_path
        self.init_db()
    
    @contextmanager
    def get_conn(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()
    
    def init_db(self):
        with self.get_conn() as conn:
            c = conn.cursor()
            
            # Пользователи
            c.execute('''CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                telegram_id INTEGER UNIQUE,
                username TEXT,
                first_name TEXT,
                joined_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                subscription_end TIMESTAMP,
                trial_used BOOLEAN DEFAULT 0
            )''')
            
            # Аккаунты (сессии)
            c.execute('''CREATE TABLE IF NOT EXISTS accounts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                phone TEXT UNIQUE NOT NULL,
                file_name TEXT NOT NULL,
                file_id TEXT NOT NULL,
                session_path TEXT,
                is_sold BOOLEAN DEFAULT 0,
                buyer_id INTEGER,
                purchase_date TIMESTAMP,
                FOREIGN KEY (buyer_id) REFERENCES users(telegram_id)
            )''')
            
            # Покупки
            c.execute('''CREATE TABLE IF NOT EXISTS purchases (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                item_type TEXT NOT NULL,
                item_id INTEGER,
                amount INTEGER NOT NULL,
                purchase_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(telegram_id)
            )''')
            
            # Настройки цен (для админа)
            c.execute('''CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )''')
            
            # Цены по умолчанию
            default_settings = [
                ('subscription_price', '60'),
                ('account_price', '50'),
                ('trial_hours', '24')
            ]
            
            for key, value in default_settings:
                c.execute('INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)', (key, value))
            
            conn.commit()
    
    # === ПОЛЬЗОВАТЕЛИ ===
    def get_user(self, telegram_id):
        with self.get_conn() as conn:
            c = conn.cursor()
            c.execute('SELECT * FROM users WHERE telegram_id = ?', (telegram_id,))
            row = c.fetchone()
            return dict(row) if row else None
    
    def create_user(self, telegram_id, username=None, first_name=None):
        with self.get_conn() as conn:
            try:
                c = conn.cursor()
                c.execute('''
                    INSERT INTO users (telegram_id, username, first_name)
                    VALUES (?, ?, ?)
                ''', (telegram_id, username, first_name))
                conn.commit()
                return True
            except:
                return False
    
    def get_all_users(self):
        with self.get_conn() as conn:
            c = conn.cursor()
            c.execute('SELECT telegram_id FROM users')
            return [row['telegram_id'] for row in c.fetchall()]
    
    # === ПОДПИСКИ ===
    def has_active_subscription(self, telegram_id):
        user = self.get_user(telegram_id)
        if not user or not user['subscription_end']:
            return False
        
        try:
            end_date = datetime.fromisoformat(user['subscription_end'])
            return end_date > datetime.now()
        except:
            return False
    
    def get_subscription_end(self, telegram_id):
        user = self.get_user(telegram_id)
        if not user:
            return None
        return user['subscription_end']
    
    def activate_subscription(self, telegram_id, days=7):
        with self.get_conn() as conn:
            c = conn.cursor()
            end_date = (datetime.now() + timedelta(days=days)).isoformat()
            c.execute('''
                UPDATE users SET subscription_end = ? WHERE telegram_id = ?
            ''', (end_date, telegram_id))
            conn.commit()
            return True
    
    def activate_trial(self, telegram_id):
        with self.get_conn() as conn:
            c = conn.cursor()
            user = self.get_user(telegram_id)
            if user and user['trial_used']:
                return False
            
            end_date = (datetime.now() + timedelta(hours=24)).isoformat()
            c.execute('''
                UPDATE users SET subscription_end = ?, trial_used = 1 WHERE telegram_id = ?
            ''', (end_date, telegram_id))
            conn.commit()
            return True
    
    def check_trial_available(self, telegram_id):
        user = self.get_user(telegram_id)
        return user and not user['trial_used']
    
    # === АККАУНТЫ ===
    def add_account(self, phone, file_name, file_id, session_path=None):
        with self.get_conn() as conn:
            try:
                c = conn.cursor()
                c.execute('''
                    INSERT INTO accounts (phone, file_name, file_id, session_path)
                    VALUES (?, ?, ?, ?)
                ''', (phone, file_name, file_id, session_path))
                conn.commit()
                return c.lastrowid
            except:
                return None
    
    def get_available_accounts(self):
        with self.get_conn() as conn:
            c = conn.cursor()
            c.execute('''
                SELECT id, phone, file_name, file_id FROM accounts 
                WHERE is_sold = 0
            ''')
            return [dict(row) for row in c.fetchall()]
    
    def get_account(self, account_id):
        with self.get_conn() as conn:
            c = conn.cursor()
            c.execute('SELECT * FROM accounts WHERE id = ?', (account_id,))
            row = c.fetchone()
            return dict(row) if row else None
    
    def buy_account(self, account_id, buyer_id):
        with self.get_conn() as conn:
            c = conn.cursor()
            c.execute('''
                UPDATE accounts 
                SET is_sold = 1, buyer_id = ?, purchase_date = CURRENT_TIMESTAMP
                WHERE id = ? AND is_sold = 0
            ''', (buyer_id, account_id))
            conn.commit()
            return c.rowcount > 0
    
    def delete_account(self, account_id):
        with self.get_conn() as conn:
            c = conn.cursor()
            c.execute('DELETE FROM accounts WHERE id = ?', (account_id,))
            conn.commit()
            return c.rowcount > 0
    
    def get_all_accounts(self):
        with self.get_conn() as conn:
            c = conn.cursor()
            c.execute('SELECT * FROM accounts ORDER BY id DESC')
            return [dict(row) for row in c.fetchall()]
    
    # === ПОКУПКИ ===
    def add_purchase(self, user_id, item_type, amount, item_id=None):
        with self.get_conn() as conn:
            c = conn.cursor()
            c.execute('''
                INSERT INTO purchases (user_id, item_type, item_id, amount)
                VALUES (?, ?, ?, ?)
            ''', (user_id, item_type, item_id, amount))
            conn.commit()
            return c.lastrowid
    
    def get_user_purchases(self, user_id):
        with self.get_conn() as conn:
            c = conn.cursor()
            c.execute('''
                SELECT * FROM purchases WHERE user_id = ? ORDER BY purchase_date DESC
            ''', (user_id,))
            return [dict(row) for row in c.fetchall()]
    
    # === НАСТРОЙКИ ===
    def get_setting(self, key):
        with self.get_conn() as conn:
            c = conn.cursor()
            c.execute('SELECT value FROM settings WHERE key = ?', (key,))
            row = c.fetchone()
            return row['value'] if row else None
    
    def update_setting(self, key, value):
        with self.get_conn() as conn:
            c = conn.cursor()
            c.execute('UPDATE settings SET value = ? WHERE key = ?', (value, key))
            conn.commit()
            return c.rowcount > 0
    
    def get_all_settings(self):
        with self.get_conn() as conn:
            c = conn.cursor()
            c.execute('SELECT * FROM settings')
            return {row['key']: row['value'] for row in c.fetchall()}
    
    # === СТАТИСТИКА ===
    def get_stats(self):
        with self.get_conn() as conn:
            c = conn.cursor()
            users = c.execute('SELECT COUNT(*) FROM users').fetchone()[0]
            active_subs = c.execute('''
                SELECT COUNT(*) FROM users 
                WHERE subscription_end > CURRENT_TIMESTAMP
            ''').fetchone()[0]
            accounts_total = c.execute('SELECT COUNT(*) FROM accounts').fetchone()[0]
            accounts_sold = c.execute('SELECT COUNT(*) FROM accounts WHERE is_sold = 1').fetchone()[0]
            purchases_total = c.execute('SELECT SUM(amount) FROM purchases').fetchone()[0] or 0
            
            return {
                'users': users,
                'active_subs': active_subs,
                'accounts_total': accounts_total,
                'accounts_sold': accounts_sold,
                'purchases_total': purchases_total
            }