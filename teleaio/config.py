# config.py
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise ValueError("❌ BOT_TOKEN не найден в .env файле!")

ADMIN_IDS = [int(id.strip()) for id in os.getenv("ADMIN_IDS", "").split(",") if id.strip()]

BASE_DIR = Path(__file__).parent
SESSIONS_DIR = BASE_DIR / "sessions"
DOWNLOADS_DIR = BASE_DIR / "downloads"
LOGS_DIR = BASE_DIR / "logs"

SESSIONS_DIR.mkdir(exist_ok=True)
DOWNLOADS_DIR.mkdir(exist_ok=True)
LOGS_DIR.mkdir(exist_ok=True)

# Telegram API данные для работы с сессиями - ОБЯЗАТЕЛЬНО УКАЖИТЕ ПРАВИЛЬНЫЕ ЗНАЧЕНИЯ!
TELEGRAM_API_ID = int(os.getenv("TELEGRAM_API_ID", "25046122"))  # Ваш API ID
TELEGRAM_API_HASH = os.getenv("TELEGRAM_API_HASH", "58d3e0f528957980a6194874f2479304")  # Ваш API HASH

# Цены по умолчанию
DEFAULT_TRIAL_HOURS = 24
DEFAULT_SUBSCRIPTION_PRICE = 60
DEFAULT_ACCOUNT_PRICE = 50

# Настройки рассылки
MAX_MESSAGES_PER_DAY = 1000  # Максимум сообщений в день на аккаунт
MESSAGE_DELAY = 300  # Задержка между сообщениями (секунд)