import asyncio
import logging
import sys
import os
from pathlib import Path
from datetime import datetime

from aiogram import Bot, Dispatcher, types, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.utils.keyboard import InlineKeyboardBuilder

import config
from database import Database
from keyboards import *
from session_handler import SessionHandler

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

bot = Bot(token=config.BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher(storage=MemoryStorage())
db = Database()
session_handler = SessionHandler()

# ================== FSM ==================
class AddAccount(StatesGroup):
    phone = State()
    code = State()
    password = State()
    file = State()

class EditPrice(StatesGroup):
    waiting_for_price = State()

class Broadcast(StatesGroup):
    waiting_for_message = State()

class Mailing(StatesGroup):
    waiting_for_text = State()
    confirm = State()
    running = State()

# ================== УТИЛИТЫ ==================
async def clean_and_send(chat_id, text, kb=None, msg_to_delete=None):
    """Отправляет сообщение и удаляет предыдущее"""
    if msg_to_delete:
        try:
            await bot.delete_message(chat_id, msg_to_delete)
        except:
            pass
    msg = await bot.send_message(chat_id, text, reply_markup=kb)
    return msg

async def safe_delete_message(chat_id, message_id):
    try:
        await bot.delete_message(chat_id, message_id)
    except:
        pass

def format_phone(phone):
    """Форматирует номер телефона"""
    if phone.startswith('+'):
        return phone
    return f"+{phone}"

def get_accounts_with_prices():
    accounts = db.get_available_accounts()
    price = int(db.get_setting('account_price') or config.DEFAULT_ACCOUNT_PRICE)
    return [{'id': a['id'], 'phone': a['phone'], 'price': price} for a in accounts]

# ================== СТАРТ ==================
@dp.message(Command("start"))
async def cmd_start(msg: types.Message):
    user_id = msg.from_user.id
    user = db.get_user(user_id)
    
    if not user:
        db.create_user(user_id, msg.from_user.username, msg.from_user.first_name)
    
    text = (
        "▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬\n"
        "     MASSENDER BOT\n"
        "▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬\n\n"
        "• Рассылка сообщений\n"
        "• Продажа аккаунтов\n"
        "• 24 часа бесплатно\n\n"
        "Выберите раздел:"
    )
    
    kb = main_kb()
    # Проверяем админа
    if msg.from_user.id in config.ADMIN_IDS:
        kb.inline_keyboard.append([InlineKeyboardButton(text="[ АДМИН ]", callback_data="admin")])
    
    await clean_and_send(msg.chat.id, text, kb)

@dp.callback_query(F.data == "back_main")
async def back_main(cb: types.CallbackQuery, state: FSMContext):
    await state.clear()
    text = "▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬\nГлавное меню\n▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬"
    await cb.answer()
    
    kb = main_kb()
    if cb.from_user.id in config.ADMIN_IDS:
        kb.inline_keyboard.append([InlineKeyboardButton(text="[ АДМИН ]", callback_data="admin")])
    
    await clean_and_send(cb.message.chat.id, text, kb, cb.message.message_id)

@dp.callback_query(F.data == "ignore")
async def ignore_cb(cb: types.CallbackQuery):
    await cb.answer()

@dp.callback_query(F.data == "cancel")
async def cancel_cb(cb: types.CallbackQuery, state: FSMContext):
    await state.clear()
    await cb.answer("❌ Отменено")
    await back_main(cb, state)

# ================== ПРОФИЛЬ ==================
@dp.callback_query(F.data == "profile")
async def profile_cb(cb: types.CallbackQuery):
    user_id = cb.from_user.id
    user = db.get_user(user_id)
    
    if not user:
        db.create_user(user_id, cb.from_user.username, cb.from_user.first_name)
        user = db.get_user(user_id)
    
    sub_end = db.get_subscription_end(user_id)
    sub_status = "✅ Активна" if db.has_active_subscription(user_id) else "❌ Нет"
    sub_date = f"до {sub_end[:16]}" if sub_end and db.has_active_subscription(user_id) else ""
    
    trial_available = db.check_trial_available(user_id)
    trial_text = "✅ Доступен" if trial_available else "❌ Использован"
    
    text = (
        f"▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬\n"
        f"ПРОФИЛЬ\n"
        f"▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬\n\n"
        f"ID: {user_id}\n"
        f"Имя: {user['first_name'] or '—'}\n"
        f"Ник: @{user['username'] or '—'}\n\n"
        f"Подписка: {sub_status} {sub_date}\n"
        f"Пробный: {trial_text}\n"
        f"Регистрация: {user['joined_date'][:16]}\n"
        f"▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬"
    )
    
    await cb.answer()
    await clean_and_send(cb.message.chat.id, text, profile_kb(), cb.message.message_id)

@dp.callback_query(F.data == "my_subscriptions")
async def my_subs_cb(cb: types.CallbackQuery):
    user_id = cb.from_user.id
    has_sub = db.has_active_subscription(user_id)
    sub_end = db.get_subscription_end(user_id)
    
    text = (
        f"▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬\n"
        f"ПОДПИСКИ\n"
        f"▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬\n\n"
    )
    
    if has_sub:
        text += f"✅ Активна до {sub_end[:16]}\n\n"
    else:
        text += "❌ Нет активных подписок\n\n"
    
    price = db.get_setting('subscription_price') or config.DEFAULT_SUBSCRIPTION_PRICE
    
    await cb.answer()
    kb = InlineKeyboardBuilder()
    kb.button(text=f"[ КУПИТЬ ЗА {price}⭐ ]", callback_data="buy_subscription")
    kb.button(text="[ НАЗАД ]", callback_data="profile")
    kb.adjust(1)
    
    await clean_and_send(cb.message.chat.id, text, kb.as_markup(), cb.message.message_id)

@dp.callback_query(F.data == "my_purchases")
async def my_purchases_cb(cb: types.CallbackQuery):
    user_id = cb.from_user.id
    purchases = db.get_user_purchases(user_id)
    
    text = (
        f"▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬\n"
        f"ИСТОРИЯ ПОКУПОК\n"
        f"▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬\n\n"
    )
    
    if purchases:
        for p in purchases[:10]:  # Последние 10
            text += f"• {p['purchase_date'][:16]} - {p['item_type']} - {p['amount']}⭐\n"
    else:
        text += "Нет покупок\n"
    
    await cb.answer()
    await clean_and_send(cb.message.chat.id, text, back_kb("profile"), cb.message.message_id)

@dp.callback_query(F.data == "buy_subscription")
async def buy_subscription_cb(cb: types.CallbackQuery):
    price = db.get_setting('subscription_price') or config.DEFAULT_SUBSCRIPTION_PRICE
    
    text = (
        f"▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬\n"
        f"ПОКУПКА ПОДПИСКИ\n"
        f"▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬\n\n"
        f"Недельная подписка: {price}⭐\n"
        f"Доступ ко всем функциям рассылки\n\n"
        f"Пробный период: 24 часа"
    )
    
    kb = InlineKeyboardBuilder()
    kb.button(text=f"[ ОПЛАТИТЬ {price}⭐ ]", callback_data="pay_subscription")
    
    if db.check_trial_available(cb.from_user.id):
        kb.button(text="[ ПРОБНЫЙ ПЕРИОД ]", callback_data="trial_subscription")
    
    kb.button(text="[ НАЗАД ]", callback_data="profile")
    kb.adjust(1)
    
    await cb.answer()
    await clean_and_send(cb.message.chat.id, text, kb.as_markup(), cb.message.message_id)

@dp.callback_query(F.data == "trial_subscription")
async def trial_subscription_cb(cb: types.CallbackQuery):
    if not db.check_trial_available(cb.from_user.id):
        await cb.answer("❌ Пробный период уже использован", show_alert=True)
        return
    
    db.activate_trial(cb.from_user.id)
    
    text = (
        f"▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬\n"
        f"ПРОБНЫЙ ПЕРИОД АКТИВИРОВАН\n"
        f"▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬\n\n"
        f"✅ 24 часа бесплатного доступа\n\n"
        f"Теперь вы можете пользоваться рассылкой"
    )
    
    await cb.answer()
    await clean_and_send(cb.message.chat.id, text, back_kb("profile"), cb.message.message_id)

# ================== ПЛАТЕЖИ (TELEGRAM STARS) ==================
@dp.callback_query(F.data == "pay_subscription")
async def pay_subscription_cb(cb: types.CallbackQuery):
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
            [types.InlineKeyboardButton(text="◀️ Отмена", callback_data="buy_subscription")]
        ])
    )
    await safe_delete_message(cb.message.chat.id, cb.message.message_id)

@dp.callback_query(F.data.startswith("buy_account_"))
async def pay_account_cb(cb: types.CallbackQuery):
    account_id = int(cb.data.replace("buy_account_", ""))
    account = db.get_account(account_id)
    
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
            [types.InlineKeyboardButton(text="◀️ Отмена", callback_data="accounts")]
        ])
    )
    await safe_delete_message(cb.message.chat.id, cb.message.message_id)

@dp.pre_checkout_query()
async def pre_checkout_handler(q: types.PreCheckoutQuery):
    await bot.answer_pre_checkout_query(q.id, ok=True)

@dp.message(F.successful_payment)
async def payment_success_handler(msg: types.Message):
    payload = msg.successful_payment.invoice_payload
    amount = msg.successful_payment.total_amount
    
    if payload.startswith("subscription_"):
        # Активация подписки
        user_id = int(payload.replace("subscription_", ""))
        db.activate_subscription(user_id, days=7)
        db.add_purchase(user_id, 'subscription', amount)
        
        text = (
            f"▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬\n"
            f"ПОДПИСКА АКТИВИРОВАНА\n"
            f"▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬\n\n"
            f"✅ Спасибо за покупку!\n"
            f"Подписка активна 7 дней\n\n"
            f"Теперь вам доступна массовая рассылка"
        )
        
    elif payload.startswith("account_"):
        # Покупка аккаунта
        parts = payload.split("_")
        account_id = int(parts[1])
        user_id = int(parts[2])
        
        account = db.get_account(account_id)
        if account and not account['is_sold']:
            db.buy_account(account_id, user_id)
            db.add_purchase(user_id, 'account', amount, account_id)
            
            # Отправляем файл сессии пользователю
            if account['file_id']:
                await bot.send_document(
                    msg.chat.id,
                    account['file_id'],
                    caption=f"✅ Ваш аккаунт: {account['phone']}\nФайл сессии прилагается"
                )
            
            text = (
                f"▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬\n"
                f"АККАУНТ ПРИОБРЕТЕН\n"
                f"▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬\n\n"
                f"✅ Аккаунт {account['phone']} ваш!\n"
                f"Файл сессии отправлен выше"
            )
        else:
            text = "❌ Аккаунт уже продан"
    
    await clean_and_send(msg.chat.id, text, main_kb())

# ================== АККАУНТЫ ==================
@dp.callback_query(F.data == "accounts")
async def accounts_cb(cb: types.CallbackQuery):
    accounts = get_accounts_with_prices()
    page = 0
    
    text = (
        f"▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬\n"
        f"ДОСТУПНЫЕ АККАУНТЫ\n"
        f"▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬\n\n"
        f"Всего: {len(accounts)}\n\n"
    )
    
    await cb.answer()
    await clean_and_send(cb.message.chat.id, text, accounts_kb(accounts, page), cb.message.message_id)

@dp.callback_query(F.data.startswith("accounts_page_"))
async def accounts_page_cb(cb: types.CallbackQuery):
    page = int(cb.data.replace("accounts_page_", ""))
    accounts = get_accounts_with_prices()
    
    text = (
        f"▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬\n"
        f"ДОСТУПНЫЕ АККАУНТЫ\n"
        f"▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬\n\n"
        f"Всего: {len(accounts)}\n\n"
    )
    
    await cb.answer()
    await clean_and_send(cb.message.chat.id, text, accounts_kb(accounts, page), cb.message.message_id)

# ================== РАССЫЛКА ==================
@dp.callback_query(F.data == "mailing")
async def mailing_cb(cb: types.CallbackQuery):
    has_sub = db.has_active_subscription(cb.from_user.id)
    
    if not has_sub:
        await cb.answer("❌ Требуется подписка", show_alert=True)
        text = (
            f"▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬\n"
            f"ДОСТУП ЗАПРЕЩЕН\n"
            f"▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬\n\n"
            f"Для использования рассылки нужна подписка\n\n"
            f"• 24 часа бесплатно\n"
            f"• {db.get_setting('subscription_price') or 60}⭐ в неделю"
        )
        kb = InlineKeyboardBuilder()
        kb.button(text="[ КУПИТЬ ПОДПИСКУ ]", callback_data="buy_subscription")
        kb.button(text="[ НАЗАД ]", callback_data="back_main")
        kb.adjust(1)
        await clean_and_send(cb.message.chat.id, text, kb.as_markup(), cb.message.message_id)
        return
    
    text = (
        f"▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬\n"
        f"МАССОВАЯ РАССЫЛКА\n"
        f"▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬\n\n"
        f"Выберите режим работы:"
    )
    
    await cb.answer()
    await clean_and_send(cb.message.chat.id, text, mailing_kb(), cb.message.message_id)

@dp.callback_query(F.data == "start_mailing")
async def start_mailing_cb(cb: types.CallbackQuery, state: FSMContext):
    await state.set_state(Mailing.waiting_for_text)
    text = (
        f"▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬\n"
        f"НАСТРОЙКА РАССЫЛКИ\n"
        f"▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬\n\n"
        f"Отправьте текст для рассылки.\n"
        f"Можно использовать эмодзи и форматирование."
    )
    await cb.answer()
    await clean_and_send(cb.message.chat.id, text, cancel_kb(), cb.message.message_id)

@dp.message(Mailing.waiting_for_text)
async def mailing_get_text(msg: types.Message, state: FSMContext):
    await state.update_data(text=msg.text)
    await state.set_state(Mailing.confirm)
    
    text_preview = msg.text[:100] + "..." if len(msg.text) > 100 else msg.text
    
    text = (
        f"▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬\n"
        f"ПОДТВЕРЖДЕНИЕ\n"
        f"▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬\n\n"
        f"Текст:\n{text_preview}\n\n"
        f"Начать рассылку?"
    )
    
    kb = InlineKeyboardBuilder()
    kb.button(text="[ ЗАПУСТИТЬ ]", callback_data="mailing_confirm_run")
    kb.button(text="[ ОТМЕНА ]", callback_data="cancel")
    kb.adjust(1)
    
    await clean_and_send(msg.chat.id, text, kb.as_markup())

@dp.callback_query(F.data == "mailing_confirm_run")
async def mailing_run(cb: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    text = data.get('text')
    
    await cb.answer("✅ Рассылка запущена")
    
    # В реальном проекте здесь запускается процесс рассылки
    # Для демо просто показываем сообщение
    
    result_text = (
        f"▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬\n"
        f"РАССЫЛКА ВЫПОЛНЕНА\n"
        f"▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬\n\n"
        f"✅ Сообщение отправлено 0 пользователям\n\n"
        f"(Демо-режим)"
    )
    
    await clean_and_send(cb.message.chat.id, result_text, back_kb("main"))
    await state.clear()

# ================== ПОДДЕРЖКА ==================
@dp.callback_query(F.data == "support")
async def support_cb(cb: types.CallbackQuery):
    text = (
        f"▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬\n"
        f"ПОДДЕРЖКА\n"
        f"▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬\n\n"
        f"По всем вопросам:\n"
        f"@admin_username\n\n"
        f"Ответ в течение 24 часов"
    )
    await cb.answer()
    await clean_and_send(cb.message.chat.id, text, back_kb("main"), cb.message.message_id)

# ================== АДМИНКА ==================
@dp.callback_query(F.data == "admin")
async def admin_cb(cb: types.CallbackQuery):
    if cb.from_user.id not in config.ADMIN_IDS:
        await cb.answer("❌ Нет доступа", show_alert=True)
        return
    
    text = (
        f"▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬\n"
        f"АДМИН-ПАНЕЛЬ\n"
        f"▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬"
    )
    
    await cb.answer()
    await clean_and_send(cb.message.chat.id, text, admin_kb(), cb.message.message_id)

@dp.callback_query(F.data == "admin_stats")
async def admin_stats_cb(cb: types.CallbackQuery):
    if cb.from_user.id not in config.ADMIN_IDS:
        await cb.answer("❌ Нет доступа", show_alert=True)
        return
    
    stats = db.get_stats()
    settings = db.get_all_settings()
    
    text = (
        f"▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬\n"
        f"СТАТИСТИКА\n"
        f"▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬\n\n"
        f"👥 Пользователей: {stats['users']}\n"
        f"✅ Активных подписок: {stats['active_subs']}\n"
        f"📦 Всего аккаунтов: {stats['accounts_total']}\n"
        f"💰 Продано аккаунтов: {stats['accounts_sold']}\n"
        f"⭐ Заработано звезд: {stats['purchases_total']}\n\n"
        f"⚙️ Настройки:\n"
        f"Подписка: {settings.get('subscription_price', '—')}⭐\n"
        f"Аккаунт: {settings.get('account_price', '—')}⭐\n"
        f"Пробный: {settings.get('trial_hours', '—')}ч"
    )
    
    await cb.answer()
    await clean_and_send(cb.message.chat.id, text, back_kb("admin"), cb.message.message_id)

@dp.callback_query(F.data == "admin_prices")
async def admin_prices_cb(cb: types.CallbackQuery):
    if cb.from_user.id not in config.ADMIN_IDS:
        await cb.answer("❌ Нет доступа", show_alert=True)
        return
    
    settings = db.get_all_settings()
    
    text = (
        f"▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬\n"
        f"УПРАВЛЕНИЕ ЦЕНАМИ\n"
        f"▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬\n\n"
        f"Текущие цены:\n"
        f"Подписка (неделя): {settings.get('subscription_price', '—')}⭐\n"
        f"Аккаунт: {settings.get('account_price', '—')}⭐\n"
        f"Пробный период: {settings.get('trial_hours', '—')}ч\n\n"
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
    await clean_and_send(cb.message.chat.id, text, cancel_kb(), cb.message.message_id)

@dp.callback_query(F.data == "admin_edit_acc_price")
async def admin_edit_acc_price_cb(cb: types.CallbackQuery, state: FSMContext):
    await state.set_state(EditPrice.waiting_for_price)
    await state.update_data(price_key='account_price', price_name='аккаунта')
    
    text = "💰 Введите новую цену аккаунта (в звездах):"
    await cb.answer()
    await clean_and_send(cb.message.chat.id, text, cancel_kb(), cb.message.message_id)

@dp.callback_query(F.data == "admin_edit_trial")
async def admin_edit_trial_cb(cb: types.CallbackQuery, state: FSMContext):
    await state.set_state(EditPrice.waiting_for_price)
    await state.update_data(price_key='trial_hours', price_name='пробного периода (часы)')
    
    text = "⏱ Введите длительность пробного периода (в часах):"
    await cb.answer()
    await clean_and_send(cb.message.chat.id, text, cancel_kb(), cb.message.message_id)

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
    
    text = f"✅ Цена {name} обновлена на {value}"
    await clean_and_send(msg.chat.id, text, back_kb("admin"))

# ================== ДОБАВЛЕНИЕ АККАУНТОВ ==================
@dp.callback_query(F.data == "admin_add_account")
async def admin_add_account_cb(cb: types.CallbackQuery, state: FSMContext):
    if cb.from_user.id not in config.ADMIN_IDS:
        await cb.answer("❌ Нет доступа", show_alert=True)
        return
    
    await state.set_state(AddAccount.phone)
    
    text = (
        f"▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬\n"
        f"ДОБАВЛЕНИЕ АККАУНТА\n"
        f"▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬\n\n"
        f"Шаг 1/2\n\n"
        f"Отправьте номер телефона в формате:\n"
        f"+71234567890"
    )
    
    await cb.answer()
    await clean_and_send(cb.message.chat.id, text, cancel_kb(), cb.message.message_id)

@dp.message(AddAccount.phone)
async def add_account_phone(msg: types.Message, state: FSMContext):
    phone = msg.text.strip()
    if not phone.startswith('+'):
        phone = '+' + phone
    
    await state.update_data(phone=phone)
    await state.set_state(AddAccount.file)
    
    text = (
        f"▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬\n"
        f"ДОБАВЛЕНИЕ АККАУНТА\n"
        f"▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬\n\n"
        f"Шаг 2/2\n\n"
        f"Отправьте файл сессии (.session)"
    )
    
    await clean_and_send(msg.chat.id, text, cancel_kb())

@dp.message(AddAccount.file, F.document)
async def add_account_file(msg: types.Message, state: FSMContext):
    doc = msg.document
    data = await state.get_data()
    phone = data.get('phone')
    
    if not doc.file_name.endswith('.session'):
        await clean_and_send(msg.chat.id, "❌ Файл должен иметь расширение .session")
        return
    
    # Сохраняем файл
    file_path = config.SESSIONS_DIR / doc.file_name
    await bot.download(doc, destination=file_path)
    
    # Добавляем в базу
    account_id = db.add_account(phone, doc.file_name, doc.file_id, str(file_path))
    
    if account_id:
        text = (
            f"▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬\n"
            f"АККАУНТ ДОБАВЛЕН\n"
            f"▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬\n\n"
            f"✅ Номер: {phone}\n"
            f"✅ Файл: {doc.file_name}\n"
            f"✅ ID: {account_id}"
        )
    else:
        text = "❌ Ошибка: такой номер уже есть в базе"
    
    await state.clear()
    await clean_and_send(msg.chat.id, text, back_kb("admin"))

@dp.message(AddAccount.file)
async def add_account_file_invalid(msg: types.Message, state: FSMContext):
    await clean_and_send(msg.chat.id, "❌ Отправьте файл")

# ================== ЗАПУСК ==================
async def main():
    logger.info("🚀 MassSender Bot запущен")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())