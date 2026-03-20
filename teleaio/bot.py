import asyncio
import logging
import sys
import os
from pathlib import Path
from datetime import datetime
import json

from aiogram import Bot, Dispatcher, types, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

import config
from database import Database
from keyboards import *
from session_manager import SessionManager
from mailing_manager import MailingManager

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

bot = Bot(token=config.BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher(storage=MemoryStorage())
db = Database()
session_manager = SessionManager()
mailing_manager = MailingManager(bot, db)

# ================== FSM СОСТОЯНИЯ ==================
class AddAccount(StatesGroup):
    phone = State()
    code = State()
    password = State()

class NewMailing(StatesGroup):
    text = State()
    media = State()
    targets = State()
    confirm = State()

class EditPrice(StatesGroup):
    waiting_for_price = State()

class AdminAddAccount(StatesGroup):
    phone = State()
    price = State()
    file = State()

class AdminBroadcast(StatesGroup):
    text = State()
    media = State()
    confirm = State()

# ================== УТИЛИТЫ ==================
async def clean_and_send(chat_id, text, kb=None, msg_to_delete=None, parse_mode=ParseMode.HTML):
    """Отправляет сообщение и удаляет предыдущее"""
    if msg_to_delete:
        try:
            await bot.delete_message(chat_id, msg_to_delete)
        except:
            pass
    
    try:
        msg = await asyncio.wait_for(
            bot.send_message(chat_id, text, reply_markup=kb, parse_mode=parse_mode),
            timeout=10
        )
        return msg
    except asyncio.TimeoutError:
        logger.error(f"Таймаут отправки сообщения в {chat_id}")
        return None
    except Exception as e:
        logger.error(f"Ошибка отправки сообщения: {e}")
        return None

async def safe_delete_message(chat_id, message_id):
    try:
        await bot.delete_message(chat_id, message_id)
    except:
        pass

def format_phone(phone):
    if phone.startswith('+'):
        return phone
    return f"+{phone}"

def get_accounts_with_prices():
    accounts = db.get_available_sell_accounts()
    return accounts

def is_admin(user_id):
    return user_id in config.ADMIN_IDS

# ================== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ==================
async def show_main_menu(chat_id, msg_id=None):
    """Показывает главное меню"""
    text = "═══════════════════════════\n<b>Главное меню</b>\n═══════════════════════════"
    await clean_and_send(chat_id, text, main_kb(), msg_id)

async def show_mailing_menu(user_id, chat_id, msg_id=None):
    """Показывает меню рассылки"""
    has_sub = db.has_active_subscription(user_id)
    
    if not has_sub:
        price = db.get_setting('subscription_price') or 60
        text = (
            f"═══════════════════════════\n"
            f"<b>ДОСТУП ЗАПРЕЩЕН</b>\n"
            f"═══════════════════════════\n\n"
            f"Для использования рассылки нужна подписка\n\n"
            f"• 24 часа бесплатно\n"
            f"• {price}⭐ в неделю"
        )
        kb = InlineKeyboardBuilder()
        kb.button(text=f"[ КУПИТЬ ПОДПИСКУ ]", callback_data="subscription_info")
        kb.button(text="[ НАЗАД В ГЛАВНОЕ ]", callback_data="back_to_main")
        kb.adjust(1)
        await clean_and_send(chat_id, text, kb.as_markup(), msg_id)
        return
    
    accounts = db.get_user_accounts(user_id)
    
    text = (
        f"═══════════════════════════\n"
        f"<b>МАССОВАЯ РАССЫЛКА</b>\n"
        f"═══════════════════════════\n\n"
        f"Аккаунтов: {len(accounts)}\n\n"
    )
    
    if accounts:
        text += "Вы можете запустить новую рассылку\nили управлять аккаунтами"
    else:
        text += "У вас нет добавленных аккаунтов.\nДобавьте аккаунт для начала рассылки"
    
    await clean_and_send(chat_id, text, mailing_kb(len(accounts) > 0), msg_id)

async def show_my_accounts(user_id, chat_id, msg_id=None):
    """Показывает список аккаунтов пользователя"""
    accounts = db.get_user_accounts(user_id)
    
    text = (
        f"═══════════════════════════\n"
        f"<b>МОИ АККАУНТЫ</b>\n"
        f"═══════════════════════════\n\n"
        f"Всего: {len(accounts)}\n\n"
    )
    
    if accounts:
        for acc in accounts:
            status = "✅" if acc['is_active'] else "❌"
            text += f"{status} {acc['phone']}\n"
            text += f"   Отправлено: {acc['total_messages_sent']}\n"
            text += f"   Сегодня: {acc['messages_sent_today']}\n"
            if acc['last_used']:
                text += f"   Последний раз: {acc['last_used'][:16]}\n"
            text += "\n"
    else:
        text += "Нет добавленных аккаунтов"
    
    builder = InlineKeyboardBuilder()
    for acc in accounts:
        builder.button(text=f"[ {acc['phone']} ]", callback_data=f"account_info_{acc['id']}")
    builder.button(text="[ + ДОБАВИТЬ АККАУНТ ]", callback_data="add_account")
    if accounts:
        builder.button(text="[ 🚪 ВЫЙТИ ИЗ ВСЕХ ]", callback_data="logout_all_accounts")
    builder.button(text="[ ◀️ НАЗАД ]", callback_data="back_to_mailing")
    builder.adjust(1)
    
    await clean_and_send(chat_id, text, builder.as_markup(), msg_id)

async def show_profile(user_id, chat_id, msg_id=None):
    """Показывает профиль пользователя"""
    user = db.get_user(user_id)
    
    if not user:
        db.create_user(user_id, None, None)
        user = db.get_user(user_id)
    
    sub_end = db.get_subscription_end(user_id)
    sub_status = "✅ Активна" if db.has_active_subscription(user_id) else "❌ Нет"
    sub_date = f"до {sub_end[:16]}" if sub_end and db.has_active_subscription(user_id) else ""
    
    trial_available = db.check_trial_available(user_id)
    trial_text = "✅ Доступен" if trial_available else "❌ Использован"
    
    accounts = db.get_user_accounts(user_id)
    
    # Добавляем кнопку админки, если пользователь админ
    if is_admin(user_id):
        builder = InlineKeyboardBuilder()
        builder.button(text="[ АДМИН-ПАНЕЛЬ ]", callback_data="admin")
        builder.button(text="[ ПОДПИСКА ]", callback_data="subscription_info")
        builder.button(text="[ ИСТОРИЯ ПОКУПОК ]", callback_data="my_purchases")
        builder.button(text="[ НАЗАД ]", callback_data="back_to_main")
        builder.adjust(1)
        kb = builder.as_markup()
    else:
        kb = profile_kb()
    
    text = (
        f"═══════════════════════════\n"
        f"<b>ПРОФИЛЬ</b>\n"
        f"═══════════════════════════\n\n"
        f"ID: <code>{user_id}</code>\n"
        f"Имя: {user['first_name'] or '—'}\n"
        f"Ник: @{user['username'] or '—'}\n\n"
        f"Подписка: {sub_status} {sub_date}\n"
        f"Пробный: {trial_text}\n"
        f"Аккаунтов: {len(accounts)}\n"
        f"Регистрация: {user['joined_date'][:16]}\n"
        f"═══════════════════════════"
    )
    
    await clean_and_send(chat_id, text, kb, msg_id)

async def show_my_mailings(user_id, chat_id, msg_id=None):
    """Показывает список рассылок пользователя"""
    mailings = db.get_user_mailings(user_id)
    
    text = (
        f"═══════════════════════════\n"
        f"<b>МОИ РАССЫЛКИ</b>\n"
        f"═══════════════════════════\n\n"
    )
    
    if mailings:
        for m in mailings[:10]:
            status_emoji = "✅" if m['status'] == 'completed' else "⏳" if m['status'] == 'running' else "⏸️"
            text += f"{status_emoji} <b>ID: {m['id']}</b> - {m['started'][:16] if m['started'] else 'Новая'}\n"
            text += f"   Статус: {m['status']}\n"
            text += f"   Отправлено: {m['messages_sent']}/{m['total_targets']}\n\n"
    else:
        text += "У вас пока нет рассылок"
    
    await clean_and_send(chat_id, text, my_mailings_kb(mailings), msg_id)

async def show_accounts(user_id, chat_id, msg_id=None):
    """Показывает список аккаунтов на продажу"""
    accounts = get_accounts_with_prices()
    page = 0
    
    text = (
        f"═══════════════════════════\n"
        f"<b>ДОСТУПНЫЕ АККАУНТЫ</b>\n"
        f"═══════════════════════════\n\n"
        f"Всего: {len(accounts)}\n\n"
        f"Цена: {db.get_setting('account_price') or 50}⭐ за аккаунт\n\n"
        f"После покупки вы получите файл сессии"
    )
    
    await clean_and_send(chat_id, text, accounts_kb(accounts, page), msg_id)

# ================== СТАРТ И НАВИГАЦИЯ ==================
@dp.message(Command("start"))
async def cmd_start(msg: types.Message):
    user_id = msg.from_user.id
    user = db.get_user(user_id)
    
    if not user:
        db.create_user(user_id, msg.from_user.username, msg.from_user.first_name)
    
    await show_main_menu(msg.chat.id)

@dp.callback_query(F.data.startswith("back_to_"))
async def universal_back_handler(cb: types.CallbackQuery, state: FSMContext):
    """Универсальный обработчик для всех кнопок назад"""
    dest = cb.data.replace("back_to_", "")
    
    await state.clear()
    session_manager.cancel_pending(cb.from_user.id)
    await cb.answer()
    
    if dest == "main":
        await show_main_menu(cb.message.chat.id, cb.message.message_id)
    elif dest == "mailing":
        await show_mailing_menu(cb.from_user.id, cb.message.chat.id, cb.message.message_id)
    elif dest == "my_accounts":
        await show_my_accounts(cb.from_user.id, cb.message.chat.id, cb.message.message_id)
    elif dest == "profile":
        await show_profile(cb.from_user.id, cb.message.chat.id, cb.message.message_id)
    elif dest == "my_mailings":
        await show_my_mailings(cb.from_user.id, cb.message.chat.id, cb.message.message_id)
    elif dest == "accounts":
        await show_accounts(cb.from_user.id, cb.message.chat.id, cb.message.message_id)
    elif dest == "admin":
        text = "═══════════════════════════\n<b>АДМИН-ПАНЕЛЬ</b>\n═══════════════════════════"
        await clean_and_send(cb.message.chat.id, text, admin_kb(), cb.message.message_id)
    else:
        await show_main_menu(cb.message.chat.id, cb.message.message_id)

@dp.callback_query(F.data == "cancel_operation")
async def cancel_operation_handler(cb: types.CallbackQuery, state: FSMContext):
    """Обработчик для отмены операций"""
    await state.clear()
    session_manager.cancel_pending(cb.from_user.id)
    await cb.answer("❌ Операция отменена")
    await show_main_menu(cb.message.chat.id, cb.message.message_id)

@dp.callback_query(F.data == "ignore")
async def ignore_cb(cb: types.CallbackQuery):
    await cb.answer()

# ================== ОСНОВНЫЕ РАЗДЕЛЫ ==================
@dp.callback_query(F.data == "mailing")
async def mailing_cb(cb: types.CallbackQuery):
    await show_mailing_menu(cb.from_user.id, cb.message.chat.id, cb.message.message_id)

@dp.callback_query(F.data == "my_accounts")
async def my_accounts_cb(cb: types.CallbackQuery):
    await show_my_accounts(cb.from_user.id, cb.message.chat.id, cb.message.message_id)

@dp.callback_query(F.data == "profile")
async def profile_cb(cb: types.CallbackQuery):
    await show_profile(cb.from_user.id, cb.message.chat.id, cb.message.message_id)

@dp.callback_query(F.data == "my_mailings")
async def my_mailings_cb(cb: types.CallbackQuery):
    await show_my_mailings(cb.from_user.id, cb.message.chat.id, cb.message.message_id)

@dp.callback_query(F.data == "accounts")
async def accounts_cb(cb: types.CallbackQuery):
    await show_accounts(cb.from_user.id, cb.message.chat.id, cb.message.message_id)

@dp.callback_query(F.data == "help")
async def help_cb(cb: types.CallbackQuery):
    text = (
        f"═══════════════════════════\n"
        f"<b>ПОМОЩЬ</b>\n"
        f"═══════════════════════════\n\n"
        f"<b>📱 Добавление аккаунтов:</b>\n"
        f"1. Нажмите 'РАССЫЛКА'\n"
        f"2. 'ДОБАВИТЬ АККАУНТ'\n"
        f"3. Введите номер и код\n\n"
        f"<b>📨 Рассылка:</b>\n"
        f"• Текст можно форматировать:\n"
        f"  <b>жирный</b>, <i>курсив</i>, <u>подчеркнутый</u>, <code>моно</code>\n"
        f"• Можно прикрепить фото или GIF\n"
        f"• Получатели: username или номер\n\n"
        f"<b>⚙️ Управление:</b>\n"
        f"• Мои рассылки - просмотр и удаление\n"
        f"• Аккаунты - покупка готовых\n"
        f"• Профиль - подписка и история"
    )
    await cb.answer()
    await clean_and_send(cb.message.chat.id, text, back_kb("main"), cb.message.message_id)

# ================== ПРОФИЛЬ И ПОДПИСКИ ==================
@dp.callback_query(F.data == "subscription_info")
async def subscription_info_cb(cb: types.CallbackQuery):
    user_id = cb.from_user.id
    price = db.get_setting('subscription_price') or config.DEFAULT_SUBSCRIPTION_PRICE
    trial_available = db.check_trial_available(user_id)
    
    sub_end = db.get_subscription_end(user_id)
    has_sub = db.has_active_subscription(user_id)
    
    text = (
        f"═══════════════════════════\n"
        f"<b>ПОДПИСКА</b>\n"
        f"═══════════════════════════\n\n"
    )
    
    if has_sub:
        text += f"✅ Активна до {sub_end[:16]}\n\n"
    else:
        text += "❌ Нет активной подписки\n\n"
    
    text += f"Цена: {price}⭐ в неделю\n"
    text += f"Пробный период: 24 часа\n\n"
    text += "Подписка дает доступ к массовой рассылке"
    
    await cb.answer()
    await clean_and_send(cb.message.chat.id, text, 
                        subscription_kb(price, trial_available), 
                        cb.message.message_id)

@dp.callback_query(F.data == "my_purchases")
async def my_purchases_cb(cb: types.CallbackQuery):
    user_id = cb.from_user.id
    purchases = db.get_user_purchases(user_id)
    
    text = (
        f"═══════════════════════════\n"
        f"<b>ИСТОРИЯ ПОКУПОК</b>\n"
        f"═══════════════════════════\n\n"
    )
    
    if purchases:
        for p in purchases[:10]:
            item = "Подписка" if p['item_type'] == 'subscription' else "Аккаунт"
            text += f"• {p['purchase_date'][:16]} - {item} - {p['amount']}⭐\n"
    else:
        text += "Нет покупок\n"
    
    await cb.answer()
    await clean_and_send(cb.message.chat.id, text, back_kb("profile"), cb.message.message_id)

@dp.callback_query(F.data == "buy_subscription")
async def buy_subscription_cb(cb: types.CallbackQuery):
    price = db.get_setting('subscription_price') or config.DEFAULT_SUBSCRIPTION_PRICE
    
    await bot.send_invoice(
        chat_id=cb.message.chat.id,
        title="Недельная подписка",
        description="Доступ к массовой рассылке на 7 дней",
        payload=f"subscription_{cb.from_user.id}",
        provider_token="",
        currency="XTR",
        prices=[types.LabeledPrice(label="Подписка", amount=int(price))],
        reply_markup=types.InlineKeyboardMarkup(inline_keyboard=[
            [types.InlineKeyboardButton(text=f"💫 Оплатить {price} ⭐", pay=True)],
            [types.InlineKeyboardButton(text="[ ОТМЕНА ]", callback_data="subscription_info")]
        ])
    )
    await safe_delete_message(cb.message.chat.id, cb.message.message_id)

@dp.callback_query(F.data == "trial_subscription")
async def trial_subscription_cb(cb: types.CallbackQuery):
    if not db.check_trial_available(cb.from_user.id):
        await cb.answer("❌ Пробный период уже использован", show_alert=True)
        return
    
    db.activate_trial(cb.from_user.id)
    
    text = (
        f"═══════════════════════════\n"
        f"<b>ПРОБНЫЙ ПЕРИОД АКТИВИРОВАН</b>\n"
        f"═══════════════════════════\n\n"
        f"✅ 24 часа бесплатного доступа\n\n"
        f"Теперь вы можете добавлять аккаунты\n"
        f"и запускать рассылку"
    )
    
    await cb.answer()
    await clean_and_send(cb.message.chat.id, text, back_kb("profile"), cb.message.message_id)

# ================== ПЛАТЕЖИ ==================
@dp.pre_checkout_query()
async def pre_checkout_handler(q: types.PreCheckoutQuery):
    await bot.answer_pre_checkout_query(q.id, ok=True)

@dp.message(F.successful_payment)
async def payment_success_handler(msg: types.Message):
    payload = msg.successful_payment.invoice_payload
    amount = msg.successful_payment.total_amount
    
    if payload.startswith("subscription_"):
        user_id = int(payload.replace("subscription_", ""))
        db.activate_subscription(user_id, days=7)
        db.add_purchase(user_id, 'subscription', amount)
        
        text = (
            f"═══════════════════════════\n"
            f"<b>ПОДПИСКА АКТИВИРОВАНА</b>\n"
            f"═══════════════════════════\n\n"
            f"✅ Спасибо за покупку!\n"
            f"Подписка активна 7 дней\n\n"
            f"Теперь вам доступна массовая рассылка"
        )
        
    elif payload.startswith("account_"):
        parts = payload.split("_")
        account_id = int(parts[1])
        user_id = int(parts[2])
        
        account = db.get_sell_account(account_id)
        if account and not account['is_sold']:
            db.buy_sell_account(account_id, user_id)
            db.add_purchase(user_id, 'account', amount, account_id)
            
            if account['file_id']:
                await bot.send_document(
                    msg.chat.id,
                    account['file_id'],
                    caption=f"✅ Ваш аккаунт: {account['phone']}\nФайл сессии прилагается"
                )
            
            text = (
                f"═══════════════════════════\n"
                f"<b>АККАУНТ ПРИОБРЕТЕН</b>\n"
                f"═══════════════════════════\n\n"
                f"✅ Аккаунт {account['phone']} ваш!\n"
                f"Файл сессии отправлен выше"
            )
        else:
            text = "❌ Аккаунт уже продан"
    
    await clean_and_send(msg.chat.id, text, main_kb())

# ================== АККАУНТЫ НА ПРОДАЖУ ==================
@dp.callback_query(F.data.startswith("accounts_page_"))
async def accounts_page_cb(cb: types.CallbackQuery):
    page = int(cb.data.replace("accounts_page_", ""))
    accounts = get_accounts_with_prices()
    
    text = (
        f"═══════════════════════════\n"
        f"<b>ДОСТУПНЫЕ АККАУНТЫ</b>\n"
        f"═══════════════════════════\n\n"
        f"Всего: {len(accounts)}\n"
        f"Страница {page+1}"
    )
    
    await cb.answer()
    await clean_and_send(cb.message.chat.id, text, accounts_kb(accounts, page), cb.message.message_id)

@dp.callback_query(F.data.startswith("buy_account_"))
async def pay_account_cb(cb: types.CallbackQuery):
    account_id = int(cb.data.replace("buy_account_", ""))
    account = db.get_sell_account(account_id)
    
    if not account or account['is_sold']:
        await cb.answer("❌ Аккаунт уже продан", show_alert=True)
        return
    
    price = db.get_setting('account_price') or config.DEFAULT_ACCOUNT_PRICE
    
    await bot.send_invoice(
        chat_id=cb.message.chat.id,
        title="Аккаунт Telegram",
        description=f"Номер: {account['phone']}",
        payload=f"account_{account_id}_{cb.from_user.id}",
        provider_token="",
        currency="XTR",
        prices=[types.LabeledPrice(label="Аккаунт", amount=int(price))],
        reply_markup=types.InlineKeyboardMarkup(inline_keyboard=[
            [types.InlineKeyboardButton(text=f"💫 Оплатить {price} ⭐", pay=True)],
            [types.InlineKeyboardButton(text="[ ОТМЕНА ]", callback_data="accounts")]
        ])
    )
    await safe_delete_message(cb.message.chat.id, cb.message.message_id)

# ================== РАССЫЛКИ ==================
async def mailing_info_cb_with_id(cb: types.CallbackQuery, mailing_id: int):
    """Показывает информацию о рассылке по ID"""
    mailing = db.get_mailing(mailing_id)
    
    if not mailing or mailing['user_id'] != cb.from_user.id:
        await cb.answer("❌ Рассылка не найдена", show_alert=True)
        return
    
    stats = db.get_queue_stats(mailing_id)
    
    media_type = "📷 Фото" if mailing.get('media_type') == 'photo' else "🎞 GIF" if mailing.get('media_type') == 'gif' else "📝 Текст"
    
    text = (
        f"═══════════════════════════\n"
        f"<b>РАССЫЛКА #{mailing_id}</b>\n"
        f"═══════════════════════════\n\n"
        f"Статус: <b>{mailing['status'].upper()}</b>\n"
        f"Тип: {media_type}\n"
        f"Всего целей: {stats['total']}\n"
        f"✅ Отправлено: {stats['sent']}\n"
        f"❌ Ошибок: {stats['failed']}\n"
        f"Начало: {mailing['started'] or '—'}\n"
        f"Завершение: {mailing['completed'] or '—'}\n\n"
    )
    
    if mailing.get('message_text'):
        text += f"Текст:\n<blockquote>{mailing['message_text'][:200]}</blockquote>\n"
    
    await cb.answer()
    await clean_and_send(cb.message.chat.id, text, mailing_info_kb(mailing_id), cb.message.message_id)

@dp.callback_query(F.data.startswith("mailing_info_"))
async def mailing_info_cb(cb: types.CallbackQuery):
    try:
        mailing_id = int(cb.data.replace("mailing_info_", ""))
    except ValueError:
        await cb.answer("❌ Неверный формат")
        return
    
    await mailing_info_cb_with_id(cb, mailing_id)

@dp.callback_query(F.data.startswith("mailing_refresh_"))
async def mailing_refresh_cb(cb: types.CallbackQuery):
    try:
        mailing_id = int(cb.data.replace("mailing_refresh_", ""))
    except ValueError:
        await cb.answer("❌ Неверный формат")
        return
    
    await mailing_info_cb_with_id(cb, mailing_id)

@dp.callback_query(F.data.startswith("mailing_pause_"))
async def mailing_pause_cb(cb: types.CallbackQuery):
    try:
        mailing_id = int(cb.data.replace("mailing_pause_", ""))
    except ValueError:
        await cb.answer("❌ Неверный формат")
        return
    
    result = await mailing_manager.stop_mailing(mailing_id)
    
    if result:
        await cb.answer("✅ Рассылка приостановлена")
    else:
        await cb.answer("❌ Не удалось приостановить", show_alert=True)
    
    await mailing_info_cb_with_id(cb, mailing_id)

@dp.callback_query(F.data.startswith("mailing_resume_"))
async def mailing_resume_cb(cb: types.CallbackQuery):
    try:
        mailing_id = int(cb.data.replace("mailing_resume_", ""))
    except ValueError:
        await cb.answer("❌ Неверный формат")
        return
    
    mailing = db.get_mailing(mailing_id)
    if not mailing or mailing['user_id'] != cb.from_user.id:
        await cb.answer("❌ Рассылка не найдена")
        return
    
    if not db.has_active_subscription(cb.from_user.id):
        await cb.answer("❌ Нужна подписка", show_alert=True)
        return
    
    result = await mailing_manager.start_mailing(
        mailing['user_id'],
        mailing_id,
        mailing.get('message_text'),
        json.loads(mailing['targets']),
        mailing.get('media_file_id'),
        mailing.get('media_type')
    )
    
    if result['success']:
        await cb.answer("✅ Рассылка возобновлена")
    else:
        await cb.answer(f"❌ {result.get('error', 'Ошибка')}", show_alert=True)
    
    await mailing_info_cb_with_id(cb, mailing_id)

@dp.callback_query(F.data.startswith("mailing_delete_"))
async def mailing_delete_cb(cb: types.CallbackQuery):
    try:
        mailing_id = int(cb.data.replace("mailing_delete_", ""))
    except ValueError:
        await cb.answer("❌ Неверный формат")
        return
    
    mailing = db.get_mailing(mailing_id)
    if not mailing or mailing['user_id'] != cb.from_user.id:
        await cb.answer("❌ Рассылка не найдена", show_alert=True)
        return
    
    await mailing_manager.stop_mailing(mailing_id)
    db.delete_mailing(mailing_id)
    
    await cb.answer("✅ Рассылка удалена")
    await show_my_mailings(cb.from_user.id, cb.message.chat.id, cb.message.message_id)

# ================== ДОБАВЛЕНИЕ АККАУНТОВ ПОЛЬЗОВАТЕЛЯ ==================
@dp.callback_query(F.data == "add_account")
async def add_account_start(cb: types.CallbackQuery, state: FSMContext):
    user_id = cb.from_user.id
    
    if not db.has_active_subscription(user_id):
        await cb.answer("❌ Нужна подписка", show_alert=True)
        return
    
    await state.set_state(AddAccount.phone)
    
    text = (
        f"═══════════════════════════\n"
        f"<b>ДОБАВЛЕНИЕ АККАУНТА</b>\n"
        f"═══════════════════════════\n\n"
        f"Шаг 1/3\n\n"
        f"Отправьте номер телефона в формате:\n"
        f"<code>+71234567890</code>\n\n"
        f"На этот номер придет код подтверждения"
    )
    
    await cb.answer()
    await clean_and_send(cb.message.chat.id, text, cancel_only_kb(), cb.message.message_id)

@dp.message(AddAccount.phone)
async def add_account_phone(msg: types.Message, state: FSMContext):
    phone = msg.text.strip()
    if not phone.startswith('+'):
        phone = '+' + phone
    
    user_id = msg.from_user.id
    session_path = config.SESSIONS_DIR / f"user_{user_id}_{phone.replace('+', '')}.session"
    
    wait_msg = await clean_and_send(msg.chat.id, "⏳ Отправляю запрос на код подтверждения...")
    result = await session_manager.create_session(user_id, phone, session_path)
    
    if result.get('success'):
        await state.update_data(phone=phone, session_path=str(session_path))
        await state.set_state(AddAccount.code)
        await safe_delete_message(msg.chat.id, wait_msg.message_id)
        await clean_and_send(msg.chat.id, "📱 Введите код из Telegram:", cancel_only_kb())
    else:
        await safe_delete_message(msg.chat.id, wait_msg.message_id)
        await clean_and_send(msg.chat.id, f"❌ {result.get('error', 'Ошибка')}", back_kb("mailing"))
        await state.clear()

@dp.message(AddAccount.code)
async def add_account_code(msg: types.Message, state: FSMContext):
    code = msg.text.strip().replace(' ', '').replace('-', '')
    user_id = msg.from_user.id
    
    wait_msg = await clean_and_send(msg.chat.id, "⏳ Проверяю код...")
    result = await session_manager.submit_code(user_id, code)
    await safe_delete_message(msg.chat.id, wait_msg.message_id)
    
    if result.get('success'):
        data = await state.get_data()
        db.add_user_account(user_id, data['phone'], data['session_path'])
        await state.clear()
        await clean_and_send(msg.chat.id, "✅ Аккаунт добавлен!", back_kb("mailing"))
    elif result.get('need_password'):
        await state.set_state(AddAccount.password)
        await clean_and_send(msg.chat.id, "🔐 Введите пароль 2FA:", cancel_only_kb())
    else:
        error_msg = result.get('error', 'Ошибка')
        kb = InlineKeyboardBuilder()
        if result.get('auto_resend'):
            kb.button(text="[ ПОПРОБОВАТЬ СНОВА ]", callback_data="retry_code")
        kb.button(text="[ НОВЫЙ КОД ]", callback_data="resend_code")
        kb.button(text="[ ОТМЕНА ]", callback_data="cancel_operation")
        kb.adjust(1)
        await clean_and_send(msg.chat.id, f"❌ {error_msg}\n\nЧто делаем?", kb.as_markup())

@dp.callback_query(F.data == "retry_code")
async def retry_code_cb(cb: types.CallbackQuery, state: FSMContext):
    await cb.answer()
    await clean_and_send(cb.message.chat.id, "📱 Введите код еще раз:", cancel_only_kb(), cb.message.message_id)

@dp.callback_query(F.data == "resend_code")
async def resend_code_cb(cb: types.CallbackQuery, state: FSMContext):
    user_id = cb.from_user.id
    await cb.answer("⏳ Запрашиваю новый код...")
    result = await session_manager.resend_code(user_id)
    if result.get('success'):
        await clean_and_send(cb.message.chat.id, "📱 Новый код отправлен! Введите код:", cancel_only_kb(), cb.message.message_id)
    else:
        await clean_and_send(cb.message.chat.id, f"❌ {result.get('error', 'Ошибка')}", back_kb("mailing"), cb.message.message_id)

@dp.message(AddAccount.password)
async def add_account_password(msg: types.Message, state: FSMContext):
    password = msg.text.strip()
    user_id = msg.from_user.id
    
    wait_msg = await clean_and_send(msg.chat.id, "⏳ Проверяю пароль...")
    result = await session_manager.submit_password(user_id, password)
    await safe_delete_message(msg.chat.id, wait_msg.message_id)
    
    if result.get('success'):
        data = await state.get_data()
        db.add_user_account(user_id, data['phone'], data['session_path'])
        await state.clear()
        await clean_and_send(msg.chat.id, "✅ Аккаунт добавлен!", back_kb("mailing"))
    else:
        await clean_and_send(msg.chat.id, f"❌ {result.get('error', 'Неверный пароль')}", cancel_only_kb())

# ================== УПРАВЛЕНИЕ АККАУНТАМИ ==================
@dp.callback_query(F.data.startswith("account_info_"))
async def account_info_cb(cb: types.CallbackQuery):
    try:
        account_id = int(cb.data.replace("account_info_", ""))
    except ValueError:
        await cb.answer("❌ Неверный формат")
        return
    
    account = db.get_user_account(account_id)
    
    if not account or account['user_id'] != cb.from_user.id:
        await cb.answer("❌ Аккаунт не найден", show_alert=True)
        return
    
    text = (
        f"═══════════════════════════\n"
        f"<b>АККАУНТ {account['phone']}</b>\n"
        f"═══════════════════════════\n\n"
        f"📱 Номер: <code>{account['phone']}</code>\n"
        f"📅 Добавлен: {account['added_date'][:16]}\n"
        f"📊 Всего отправлено: {account['total_messages_sent']}\n"
        f"📈 Отправлено сегодня: {account['messages_sent_today']}\n"
        f"⏱ Последнее использование: {account['last_used'] or '—'}\n"
        f"✅ Статус: {'Активен' if account['is_active'] else 'Неактивен'}\n"
    )
    
    builder = InlineKeyboardBuilder()
    if account['is_active']:
        builder.button(text="[ 🚪 ВЫЙТИ ]", callback_data=f"logout_account_{account_id}")
    builder.button(text="[ ❌ УДАЛИТЬ ]", callback_data=f"delete_account_{account_id}")
    builder.button(text="[ ◀️ НАЗАД ]", callback_data="back_to_my_accounts")
    builder.adjust(1)
    
    await cb.answer()
    await clean_and_send(cb.message.chat.id, text, builder.as_markup(), cb.message.message_id)

@dp.callback_query(F.data.startswith("logout_account_"))
async def logout_account_cb(cb: types.CallbackQuery):
    try:
        account_id = int(cb.data.replace("logout_account_", ""))
    except ValueError:
        await cb.answer("❌ Неверный формат")
        return
    
    account = db.get_user_account(account_id)
    
    if not account or account['user_id'] != cb.from_user.id:
        await cb.answer("❌ Аккаунт не найден", show_alert=True)
        return
    
    db.deactivate_account(account_id)
    
    await cb.answer(f"✅ Выход выполнен")
    await show_my_accounts(cb.from_user.id, cb.message.chat.id, cb.message.message_id)

@dp.callback_query(F.data == "logout_all_accounts")
async def logout_all_accounts_cb(cb: types.CallbackQuery):
    user_id = cb.from_user.id
    
    builder = InlineKeyboardBuilder()
    builder.button(text="[ ✅ ПОДТВЕРДИТЬ ]", callback_data="confirm_logout_all")
    builder.button(text="[ ❌ ОТМЕНА ]", callback_data="back_to_my_accounts")
    builder.adjust(1)
    
    text = (
        f"═══════════════════════════\n"
        f"<b>ПОДТВЕРЖДЕНИЕ</b>\n"
        f"═══════════════════════════\n\n"
        f"Вы уверены, что хотите выйти из ВСЕХ аккаунтов?\n\n"
        f"Сессии останутся в системе, но будут деактивированы."
    )
    
    await cb.answer()
    await clean_and_send(cb.message.chat.id, text, builder.as_markup(), cb.message.message_id)

@dp.callback_query(F.data == "confirm_logout_all")
async def confirm_logout_all_cb(cb: types.CallbackQuery):
    user_id = cb.from_user.id
    
    db.deactivate_all_accounts(user_id)
    
    await cb.answer("✅ Выход выполнен из всех аккаунтов")
    await show_my_accounts(cb.from_user.id, cb.message.chat.id, cb.message.message_id)

@dp.callback_query(F.data.startswith("delete_account_"))
async def delete_account_cb(cb: types.CallbackQuery):
    try:
        account_id = int(cb.data.replace("delete_account_", ""))
    except ValueError:
        await cb.answer("❌ Неверный формат")
        return
    
    account = db.get_user_account(account_id)
    
    if not account or account['user_id'] != cb.from_user.id:
        await cb.answer("❌ Аккаунт не найден", show_alert=True)
        return
    
    try:
        os.remove(account['session_path'])
    except:
        pass
    
    db.delete_user_account(account_id, cb.from_user.id)
    
    await cb.answer("✅ Аккаунт удален")
    await show_my_accounts(cb.from_user.id, cb.message.chat.id, cb.message.message_id)

# ================== НОВАЯ РАССЫЛКА ==================
@dp.callback_query(F.data == "new_mailing")
async def new_mailing_start(cb: types.CallbackQuery, state: FSMContext):
    user_id = cb.from_user.id
    accounts = db.get_user_accounts(user_id)
    
    if not accounts:
        await cb.answer("❌ Сначала добавьте аккаунт", show_alert=True)
        return
    
    await state.set_state(NewMailing.text)
    
    text = (
        f"═══════════════════════════\n"
        f"<b>НОВАЯ РАССЫЛКА</b>\n"
        f"═══════════════════════════\n\n"
        f"Шаг 1/4\n\n"
        f"Отправьте <b>текст</b> для рассылки.\n\n"
        f"<b>Форматирование:</b>\n"
        f"• <b>жирный</b> - &lt;b&gt;текст&lt;/b&gt;\n"
        f"• <i>курсив</i> - &lt;i&gt;текст&lt;/i&gt;\n"
        f"• <u>подчеркнутый</u> - &lt;u&gt;текст&lt;/u&gt;\n"
        f"• <code>моно</code> - &lt;code&gt;текст&lt;/code&gt;\n\n"
        f"Или отправьте команду /skip, чтобы пропустить текст"
    )
    
    await cb.answer()
    await clean_and_send(cb.message.chat.id, text, cancel_only_kb(), cb.message.message_id)

@dp.message(NewMailing.text)
async def new_mailing_text(msg: types.Message, state: FSMContext):
    if msg.text == "/skip":
        await state.update_data(text=None)
    else:
        await state.update_data(text=msg.text)
    
    await state.set_state(NewMailing.media)
    
    text = (
        f"═══════════════════════════\n"
        f"<b>НОВАЯ РАССЫЛКА</b>\n"
        f"═══════════════════════════\n\n"
        f"Шаг 2/4\n\n"
        f"Отправьте <b>фото или GIF</b> (опционально)\n\n"
        f"Или отправьте /skip, чтобы продолжить без медиа"
    )
    
    await clean_and_send(msg.chat.id, text, cancel_only_kb())

@dp.message(NewMailing.media, F.photo | F.animation | F.document)
async def new_mailing_media(msg: types.Message, state: FSMContext):
    media_file_id = None
    media_type = None
    
    if msg.photo:
        media_file_id = msg.photo[-1].file_id
        media_type = 'photo'
    elif msg.animation:
        media_file_id = msg.animation.file_id
        media_type = 'gif'
    elif msg.document and msg.document.mime_type in ['image/gif', 'image/jpeg', 'image/png']:
        media_file_id = msg.document.file_id
        media_type = 'document'
    
    if media_file_id:
        await state.update_data(media_file_id=media_file_id, media_type=media_type)
        await state.set_state(NewMailing.targets)
        
        text = (
            f"═══════════════════════════\n"
            f"<b>НОВАЯ РАССЫЛКА</b>\n"
            f"═══════════════════════════\n\n"
            f"Шаг 3/4\n\n"
            f"Отправьте список <b>получателей</b>.\n"
            f"Каждый получатель с новой строки.\n\n"
            f"<b>Форматы:</b>\n"
            f"• @username\n"
            f"• +71234567890\n"
            f"• 71234567890"
        )
        await clean_and_send(msg.chat.id, text, cancel_only_kb())
    else:
        await clean_and_send(msg.chat.id, "❌ Отправьте фото или GIF")

@dp.message(NewMailing.media)
async def new_mailing_media_skip(msg: types.Message, state: FSMContext):
    if msg.text == "/skip":
        await state.update_data(media_file_id=None, media_type=None)
        await state.set_state(NewMailing.targets)
        
        text = (
            f"═══════════════════════════\n"
            f"<b>НОВАЯ РАССЫЛКА</b>\n"
            f"═══════════════════════════\n\n"
            f"Шаг 3/4\n\n"
            f"Отправьте список <b>получателей</b>.\n"
            f"Каждый получатель с новой строки.\n\n"
            f"<b>Форматы:</b>\n"
            f"• @username\n"
            f"• +71234567890\n"
            f"• 71234567890"
        )
        await clean_and_send(msg.chat.id, text, cancel_only_kb())
    else:
        await clean_and_send(msg.chat.id, "❌ Отправьте фото, GIF или /skip")

@dp.message(NewMailing.targets)
async def new_mailing_targets(msg: types.Message, state: FSMContext):
    targets = [line.strip() for line in msg.text.split('\n') if line.strip()]
    
    if len(targets) > 100:
        await clean_and_send(msg.chat.id, "❌ Максимум 100 получателей за раз")
        return
    
    await state.update_data(targets=targets)
    await state.set_state(NewMailing.confirm)
    
    data = await state.get_data()
    text_preview = data.get('text', '')[:100] + "..." if data.get('text') and len(data['text']) > 100 else data.get('text', '—')
    media_info = "📷 С фото" if data.get('media_type') in ['photo', 'document'] else "🎞 С GIF" if data.get('media_type') == 'gif' else "📝 Без медиа"
    
    text = (
        f"═══════════════════════════\n"
        f"<b>ПОДТВЕРЖДЕНИЕ</b>\n"
        f"═══════════════════════════\n\n"
        f"<b>Текст:</b>\n{text_preview}\n\n"
        f"<b>Медиа:</b> {media_info}\n"
        f"<b>Получателей:</b> {len(targets)}\n\n"
        f"Запустить рассылку?"
    )
    
    kb = InlineKeyboardBuilder()
    kb.button(text="[ ЗАПУСТИТЬ ]", callback_data="mailing_confirm_run")
    kb.button(text="[ ОТМЕНА ]", callback_data="cancel_operation")
    kb.adjust(1)
    
    await clean_and_send(msg.chat.id, text, kb.as_markup())

@dp.callback_query(F.data == "mailing_confirm_run")
async def mailing_run(cb: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    user_id = cb.from_user.id
    
    mailing_id = db.create_mailing(
        user_id, 
        data.get('text'), 
        data['targets'],
        data.get('media_file_id'),
        data.get('media_type')
    )
    
    result = await mailing_manager.start_mailing(
        user_id, 
        mailing_id,
        data.get('text'), 
        data['targets'],
        data.get('media_file_id'),
        data.get('media_type')
    )
    
    if result['success']:
        text = (
            f"═══════════════════════════\n"
            f"<b>РАССЫЛКА ЗАПУЩЕНА</b>\n"
            f"═══════════════════════════\n\n"
            f"✅ ID: <b>{mailing_id}</b>\n"
            f"Получателей: {len(data['targets'])}\n\n"
            f"Статус можно отслеживать в разделе\n"
            f"'Мои рассылки'"
        )
    else:
        text = f"❌ Ошибка: {result['error']}"
    
    await state.clear()
    await clean_and_send(cb.message.chat.id, text, back_kb("mailing"), cb.message.message_id)

# ================== АДМИНКА ==================
@dp.callback_query(F.data == "admin")
async def admin_cb(cb: types.CallbackQuery):
    if not is_admin(cb.from_user.id):
        await cb.answer("❌ Нет доступа", show_alert=True)
        return
    
    text = "═══════════════════════════\n<b>АДМИН-ПАНЕЛЬ</b>\n═══════════════════════════"
    await cb.answer()
    await clean_and_send(cb.message.chat.id, text, admin_kb(), cb.message.message_id)

@dp.callback_query(F.data == "admin_stats")
async def admin_stats_cb(cb: types.CallbackQuery):
    if not is_admin(cb.from_user.id):
        await cb.answer("❌ Нет доступа", show_alert=True)
        return
    
    stats = db.get_stats()
    settings = db.get_all_settings()
    
    text = (
        f"═══════════════════════════\n"
        f"<b>СТАТИСТИКА</b>\n"
        f"═══════════════════════════\n\n"
        f"👥 Пользователей: {stats['users']}\n"
        f"✅ Активных подписок: {stats['active_subs']}\n"
        f"📦 Аккаунтов юзеров: {stats['user_accounts']}\n"
        f"💰 Аккаунтов на продажу: {stats['sell_accounts_total']}\n"
        f"💸 Продано аккаунтов: {stats['sell_accounts_sold']}\n"
        f"📨 Рассылок: {stats['mailings']}\n"
        f"✉️ Отправлено сообщений: {stats['messages_sent']}\n"
        f"⭐ Заработано звезд: {stats['purchases_total']}\n\n"
        f"<b>⚙️ Настройки:</b>\n"
        f"Подписка: {settings.get('subscription_price', '—')}⭐\n"
        f"Аккаунт: {settings.get('account_price', '—')}⭐\n"
        f"Пробный: {settings.get('trial_hours', '—')}ч\n"
        f"Лимит в день: {settings.get('max_messages_per_day', '—')}\n"
        f"Задержка: {settings.get('message_delay', '—')}с"
    )
    
    await cb.answer()
    await clean_and_send(cb.message.chat.id, text, back_kb("admin"), cb.message.message_id)

@dp.callback_query(F.data == "admin_prices")
async def admin_prices_cb(cb: types.CallbackQuery):
    if not is_admin(cb.from_user.id):
        await cb.answer("❌ Нет доступа", show_alert=True)
        return
    
    settings = db.get_all_settings()
    
    text = (
        f"═══════════════════════════\n"
        f"<b>УПРАВЛЕНИЕ ЦЕНАМИ</b>\n"
        f"═══════════════════════════\n\n"
        f"Текущие настройки:\n"
        f"Подписка: {settings.get('subscription_price', '—')}⭐\n"
        f"Аккаунт: {settings.get('account_price', '—')}⭐\n"
        f"Пробный: {settings.get('trial_hours', '—')}ч\n"
        f"Лимит в день: {settings.get('max_messages_per_day', '—')}\n"
        f"Задержка: {settings.get('message_delay', '—')}с\n\n"
        f"Выберите что изменить:"
    )
    
    await cb.answer()
    await clean_and_send(cb.message.chat.id, text, admin_prices_kb(), cb.message.message_id)

@dp.callback_query(F.data == "admin_edit_sub_price")
async def admin_edit_sub_price_cb(cb: types.CallbackQuery, state: FSMContext):
    await state.set_state(EditPrice.waiting_for_price)
    await state.update_data(price_key='subscription_price', price_name='подписки')
    text = "💰 Введите новую цену подписки (в звездах):"
    await cb.answer()
    await clean_and_send(cb.message.chat.id, text, cancel_only_kb(), cb.message.message_id)

@dp.callback_query(F.data == "admin_edit_acc_price")
async def admin_edit_acc_price_cb(cb: types.CallbackQuery, state: FSMContext):
    await state.set_state(EditPrice.waiting_for_price)
    await state.update_data(price_key='account_price', price_name='аккаунта')
    text = "💰 Введите новую цену аккаунта (в звездах):"
    await cb.answer()
    await clean_and_send(cb.message.chat.id, text, cancel_only_kb(), cb.message.message_id)

@dp.callback_query(F.data == "admin_edit_trial")
async def admin_edit_trial_cb(cb: types.CallbackQuery, state: FSMContext):
    await state.set_state(EditPrice.waiting_for_price)
    await state.update_data(price_key='trial_hours', price_name='пробного периода (часы)')
    text = "⏱ Введите длительность пробного периода (в часах):"
    await cb.answer()
    await clean_and_send(cb.message.chat.id, text, cancel_only_kb(), cb.message.message_id)

@dp.callback_query(F.data == "admin_edit_limits")
async def admin_edit_limits_cb(cb: types.CallbackQuery, state: FSMContext):
    kb = InlineKeyboardBuilder()
    kb.button(text="[ ЛИМИТ СООБЩЕНИЙ ]", callback_data="admin_edit_msg_limit")
    kb.button(text="[ ЗАДЕРЖКА ]", callback_data="admin_edit_delay")
    kb.button(text="[ НАЗАД ]", callback_data="admin_prices")
    kb.adjust(1)
    text = "Выберите что изменить:"
    await cb.answer()
    await clean_and_send(cb.message.chat.id, text, kb.as_markup(), cb.message.message_id)

@dp.callback_query(F.data == "admin_edit_msg_limit")
async def admin_edit_msg_limit_cb(cb: types.CallbackQuery, state: FSMContext):
    await state.set_state(EditPrice.waiting_for_price)
    await state.update_data(price_key='max_messages_per_day', price_name='лимита сообщений в день')
    text = "📊 Введите новый лимит сообщений в день на один аккаунт:"
    await cb.answer()
    await clean_and_send(cb.message.chat.id, text, cancel_only_kb(), cb.message.message_id)

@dp.callback_query(F.data == "admin_edit_delay")
async def admin_edit_delay_cb(cb: types.CallbackQuery, state: FSMContext):
    await state.set_state(EditPrice.waiting_for_price)
    await state.update_data(price_key='message_delay', price_name='задержки между сообщениями (сек)')
    current_delay = db.get_setting('message_delay') or 3
    text = f"⏱ Введите новую задержку между сообщениями в секундах\n\nТекущая: {current_delay} сек"
    await cb.answer()
    await clean_and_send(cb.message.chat.id, text, cancel_only_kb(), cb.message.message_id)

@dp.message(EditPrice.waiting_for_price)
async def edit_price_handler(msg: types.Message, state: FSMContext):
    try:
        value = int(msg.text)
        if value < 0:
            raise ValueError
    except:
        await clean_and_send(msg.chat.id, "❌ Введите положительное число")
        return
    
    data = await state.get_data()
    key = data.get('price_key')
    name = data.get('price_name')
    
    db.update_setting(key, str(value))
    await state.clear()
    
    text = f"✅ {name} обновлена на {value}"
    await clean_and_send(msg.chat.id, text, back_kb("admin"))

# ================== ДОБАВЛЕНИЕ АККАУНТОВ АДМИНОМ ==================
@dp.callback_query(F.data == "admin_add_account")
async def admin_add_account_start(cb: types.CallbackQuery, state: FSMContext):
    if not is_admin(cb.from_user.id):
        await cb.answer("❌ Нет доступа", show_alert=True)
        return
    
    await state.set_state(AdminAddAccount.phone)
    
    text = (
        f"═══════════════════════════\n"
        f"<b>ДОБАВЛЕНИЕ АККАУНТА</b>\n"
        f"═══════════════════════════\n\n"
        f"Шаг 1/3\n\n"
        f"Отправьте номер телефона в формате:\n"
        f"<code>+71234567890</code>"
    )
    
    await cb.answer()
    await clean_and_send(cb.message.chat.id, text, cancel_only_kb(), cb.message.message_id)

@dp.message(AdminAddAccount.phone)
async def admin_add_account_phone(msg: types.Message, state: FSMContext):
    phone = msg.text.strip()
    if not phone.startswith('+'):
        phone = '+' + phone
    
    await state.update_data(phone=phone)
    await state.set_state(AdminAddAccount.price)
    
    text = "💰 Введите цену аккаунта (в звездах):"
    await clean_and_send(msg.chat.id, text, cancel_only_kb())

@dp.message(AdminAddAccount.price)
async def admin_add_account_price(msg: types.Message, state: FSMContext):
    try:
        price = int(msg.text)
        if price < 0:
            raise ValueError
    except:
        await clean_and_send(msg.chat.id, "❌ Введите положительное число")
        return
    
    await state.update_data(price=price)
    await state.set_state(AdminAddAccount.file)
    
    text = "📁 Отправьте файл сессии (.session):"
    await clean_and_send(msg.chat.id, text, cancel_only_kb())

@dp.message(AdminAddAccount.file, F.document)
async def admin_add_account_file(msg: types.Message, state: FSMContext):
    doc = msg.document
    data = await state.get_data()
    phone = data.get('phone')
    price = data.get('price')
    
    if not doc.file_name.endswith('.session'):
        await clean_and_send(msg.chat.id, "❌ Файл должен иметь расширение .session")
        return
    
    file_path = config.SESSIONS_DIR / doc.file_name
    await bot.download(doc, destination=file_path)
    
    account_id = db.add_sell_account(phone, doc.file_name, doc.file_id, price, str(file_path))
    
    if account_id:
        text = (
            f"═══════════════════════════\n"
            f"<b>АККАУНТ ДОБАВЛЕН</b>\n"
            f"═══════════════════════════\n\n"
            f"✅ Номер: <code>{phone}</code>\n"
            f"✅ Цена: {price}⭐\n"
            f"✅ Файл: {doc.file_name}\n"
            f"✅ ID: {account_id}"
        )
    else:
        text = "❌ Ошибка: такой номер уже есть в базе"
    
    await state.clear()
    await clean_and_send(msg.chat.id, text, back_kb("admin"))

@dp.message(AdminAddAccount.file)
async def admin_add_account_file_invalid(msg: types.Message, state: FSMContext):
    await clean_and_send(msg.chat.id, "❌ Отправьте файл")

# ================== РАССЫЛКА ВСЕМ ==================
@dp.callback_query(F.data == "admin_broadcast")
async def admin_broadcast_start(cb: types.CallbackQuery, state: FSMContext):
    if not is_admin(cb.from_user.id):
        await cb.answer("❌ Нет доступа", show_alert=True)
        return
    
    await state.set_state(AdminBroadcast.text)
    
    text = (
        f"═══════════════════════════\n"
        f"<b>РАССЫЛКА ВСЕМ ПОЛЬЗОВАТЕЛЯМ</b>\n"
        f"═══════════════════════════\n\n"
        f"Шаг 1/3\n\n"
        f"Отправьте <b>текст</b> для рассылки:"
    )
    
    await cb.answer()
    await clean_and_send(cb.message.chat.id, text, cancel_only_kb(), cb.message.message_id)

@dp.message(AdminBroadcast.text)
async def admin_broadcast_text(msg: types.Message, state: FSMContext):
    await state.update_data(text=msg.text)
    await state.set_state(AdminBroadcast.media)
    
    text = (
        f"═══════════════════════════\n"
        f"<b>РАССЫЛКА ВСЕМ ПОЛЬЗОВАТЕЛЯМ</b>\n"
        f"═══════════════════════════\n\n"
        f"Шаг 2/3\n\n"
        f"Отправьте <b>фото или GIF</b> (опционально)\n\n"
        f"Или отправьте /skip"
    )
    await clean_and_send(msg.chat.id, text, cancel_only_kb())

@dp.message(AdminBroadcast.media, F.photo | F.animation | F.document)
async def admin_broadcast_media(msg: types.Message, state: FSMContext):
    media_file_id = None
    media_type = None
    
    if msg.photo:
        media_file_id = msg.photo[-1].file_id
        media_type = 'photo'
    elif msg.animation:
        media_file_id = msg.animation.file_id
        media_type = 'gif'
    elif msg.document:
        media_file_id = msg.document.file_id
        media_type = 'document'
    
    await state.update_data(media_file_id=media_file_id, media_type=media_type)
    await state.set_state(AdminBroadcast.confirm)
    
    data = await state.get_data()
    text_preview = data.get('text', '')[:100] + "..." if len(data['text']) > 100 else data['text']
    media_info = "📷 С фото" if media_type in ['photo', 'document'] else "🎞 С GIF" if media_type == 'gif' else "📝 Без медиа"
    
    text = (
        f"═══════════════════════════\n"
        f"<b>ПОДТВЕРЖДЕНИЕ</b>\n"
        f"═══════════════════════════\n\n"
        f"<b>Текст:</b>\n{text_preview}\n\n"
        f"<b>Медиа:</b> {media_info}\n\n"
        f"Отправить всем пользователям?"
    )
    
    kb = InlineKeyboardBuilder()
    kb.button(text="[ ОТПРАВИТЬ ]", callback_data="broadcast_confirm_run")
    kb.button(text="[ ОТМЕНА ]", callback_data="cancel_operation")
    kb.adjust(1)
    
    await clean_and_send(msg.chat.id, text, kb.as_markup())

@dp.message(AdminBroadcast.media)
async def admin_broadcast_media_skip(msg: types.Message, state: FSMContext):
    if msg.text == "/skip":
        await state.update_data(media_file_id=None, media_type=None)
        await state.set_state(AdminBroadcast.confirm)
        
        data = await state.get_data()
        text_preview = data.get('text', '')[:100] + "..." if len(data['text']) > 100 else data['text']
        
        text = (
            f"═══════════════════════════\n"
            f"<b>ПОДТВЕРЖДЕНИЕ</b>\n"
            f"═══════════════════════════\n\n"
            f"<b>Текст:</b>\n{text_preview}\n\n"
            f"<b>Медиа:</b> Без медиа\n\n"
            f"Отправить всем пользователям?"
        )
        
        kb = InlineKeyboardBuilder()
        kb.button(text="[ ОТПРАВИТЬ ]", callback_data="broadcast_confirm_run")
        kb.button(text="[ ОТМЕНА ]", callback_data="cancel_operation")
        kb.adjust(1)
        
        await clean_and_send(msg.chat.id, text, kb.as_markup())
    else:
        await clean_and_send(msg.chat.id, "❌ Отправьте фото, GIF или /skip")

@dp.callback_query(F.data == "broadcast_confirm_run")
async def admin_broadcast_run(cb: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    text = data['text']
    media_file_id = data.get('media_file_id')
    media_type = data.get('media_type')
    
    users = db.get_all_users()
    sent = 0
    failed = 0
    
    await cb.answer("⏳ Рассылка запущена...")
    
    for user_id in users:
        try:
            if media_file_id and media_type == 'photo':
                await bot.send_photo(user_id, media_file_id, caption=text, parse_mode=ParseMode.HTML)
            elif media_file_id and media_type == 'gif':
                await bot.send_animation(user_id, media_file_id, caption=text, parse_mode=ParseMode.HTML)
            elif media_file_id:
                await bot.send_document(user_id, media_file_id, caption=text, parse_mode=ParseMode.HTML)
            else:
                await bot.send_message(user_id, text, parse_mode=ParseMode.HTML)
            sent += 1
            await asyncio.sleep(0.5)
        except Exception as e:
            logger.error(f"Ошибка отправки пользователю {user_id}: {e}")
            failed += 1
    
    result_text = (
        f"═══════════════════════════\n"
        f"<b>РАССЫЛКА ЗАВЕРШЕНА</b>\n"
        f"═══════════════════════════\n\n"
        f"✅ Отправлено: {sent}\n"
        f"❌ Не удалось: {failed}"
    )
    
    await state.clear()
    await clean_and_send(cb.message.chat.id, result_text, back_kb("admin"), cb.message.message_id)

# ================== ЗАПУСК ==================
async def on_startup():
    db.reset_daily_messages()
    db.reset_accounts_daily_messages()
    logger.info("✅ Дневные счетчики сброшены")

async def on_shutdown():
    await session_manager.cleanup_clients()
    mailing_manager.shutdown()
    logger.info("👋 Бот остановлен")

async def main():
    await on_startup()
    logger.info("🚀 MassSender Bot запущен")
    try:
        await dp.start_polling(bot)
    finally:
        await on_shutdown()

if __name__ == "__main__":
    asyncio.run(main())