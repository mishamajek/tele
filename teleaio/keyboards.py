from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder

def main_kb():
    builder = InlineKeyboardBuilder()
    builder.button(text="[ РАССЫЛКА ]", callback_data="mailing")
    builder.button(text="[ ПРОФИЛЬ ]", callback_data="profile")
    builder.button(text="[ ПОМОЩЬ ]", callback_data="help")
    builder.button(text="[ 📢 НОВОСТИ ]", callback_data="news_channel")
    builder.adjust(1, 2, 1)
    return builder.as_markup()

def mailing_kb(has_accounts=False, has_active=False):
    builder = InlineKeyboardBuilder()
    if has_accounts:
        if has_active:
            builder.button(text="[ 📊 МОИ РАССЫЛКИ ]", callback_data="my_mailings")
        else:
            builder.button(text="[ 🆕 НОВАЯ РАССЫЛКА ]", callback_data="new_mailing")
            builder.button(text="[ 📊 МОИ РАССЫЛКИ ]", callback_data="my_mailings")
        builder.button(text="[ ⚙️ УПРАВЛЕНИЕ АККАУНТАМИ ]", callback_data="my_accounts")
    else:
        builder.button(text="[ + ДОБАВИТЬ АККАУНТ ]", callback_data="add_account")
    builder.button(text="[ ◀️ НАЗАД ]", callback_data="back_to_main")
    builder.adjust(1)
    return builder.as_markup()

def profile_kb():
    builder = InlineKeyboardBuilder()
    builder.button(text="[ ПОДПИСКА ]", callback_data="subscription_info")
    builder.button(text="[ ИСТОРИЯ ПОКУПОК ]", callback_data="my_purchases")
    builder.button(text="[ НАЗАД ]", callback_data="back_to_main")
    builder.adjust(1)
    return builder.as_markup()

def subscription_kb(price, trial_available=False):
    builder = InlineKeyboardBuilder()
    builder.button(text=f"[ КУПИТЬ ЗА {price}⭐ ]", callback_data="buy_subscription")
    if trial_available:
        builder.button(text="[ ПРОБНЫЙ ПЕРИОД ]", callback_data="trial_subscription")
    builder.button(text="[ НАЗАД ]", callback_data="back_to_profile")
    builder.adjust(1)
    return builder.as_markup()

def my_mailings_kb(mailings):
    builder = InlineKeyboardBuilder()
    if mailings:
        for m in mailings[:10]:
            status = "✅" if m['status'] == 'completed' else "🟢" if m['status'] == 'running' else "⏸️"
            name = m.get('name', 'Без названия')
            if len(name) > 20:
                name = name[:17] + "..."
            builder.button(
                text=f"{status} {name} (ID: {m['id']}) - {m.get('interval', 300)} сек", 
                callback_data=f"mailing_info_{m['id']}"
            )
    else:
        builder.button(text="[ НЕТ РАССЫЛОК ]", callback_data="ignore")
    builder.button(text="[ ◀️ НАЗАД ]", callback_data="back_to_mailing")
    builder.adjust(1)
    return builder.as_markup()

def mailing_info_kb(mailing_id, is_active=False):
    builder = InlineKeyboardBuilder()
    if is_active:
        builder.button(text="[ ⏸️ ОСТАНОВИТЬ ]", callback_data=f"mailing_stop_{mailing_id}")
    else:
        builder.button(text="[ ▶️ ВОЗОБНОВИТЬ ]", callback_data=f"mailing_resume_{mailing_id}")
    builder.button(text="[ ✏️ ИЗМЕНИТЬ НАЗВАНИЕ ]", callback_data=f"mailing_rename_{mailing_id}")
    builder.button(text="[ ⏱ ИЗМЕНИТЬ ИНТЕРВАЛ ]", callback_data=f"mailing_interval_{mailing_id}")
    builder.button(text="[ ❌ УДАЛИТЬ ]", callback_data=f"mailing_delete_{mailing_id}")
    builder.button(text="[ 🔄 ОБНОВИТЬ ]", callback_data=f"mailing_info_{mailing_id}")
    builder.button(text="[ ◀️ НАЗАД ]", callback_data="back_to_my_mailings")
    builder.adjust(1)
    return builder.as_markup()

def my_accounts_kb(accounts):
    builder = InlineKeyboardBuilder()
    for acc in accounts:
        builder.button(
            text=f"[ {acc['phone']} ]", 
            callback_data=f"account_info_{acc['id']}"
        )
    builder.button(text="[ + ДОБАВИТЬ АККАУНТ ]", callback_data="add_account")
    builder.button(text="[ ◀️ НАЗАД ]", callback_data="back_to_mailing")
    builder.adjust(1)
    return builder.as_markup()

def admin_kb():
    builder = InlineKeyboardBuilder()
    builder.button(text="[ СТАТИСТИКА ]", callback_data="admin_stats")
    builder.button(text="[ УПРАВЛЕНИЕ ЦЕНАМИ ]", callback_data="admin_prices")
    builder.button(text="[ РАССЫЛКА ВСЕМ ]", callback_data="admin_broadcast")
    builder.button(text="[ ◀️ НАЗАД ]", callback_data="back_to_main")
    builder.adjust(1)
    return builder.as_markup()

def admin_prices_kb():
    builder = InlineKeyboardBuilder()
    builder.button(text="[ ЦЕНА ПОДПИСКИ ]", callback_data="admin_edit_sub_price")
    builder.button(text="[ ПРОБНЫЙ ПЕРИОД ]", callback_data="admin_edit_trial")
    builder.button(text="[ ЛИМИТЫ РАССЫЛКИ ]", callback_data="admin_edit_limits")
    builder.button(text="[ ◀️ НАЗАД ]", callback_data="back_to_admin")
    builder.adjust(1)
    return builder.as_markup()

def cancel_only_kb():
    builder = InlineKeyboardBuilder()
    builder.button(text="[ ОТМЕНА ]", callback_data="cancel_operation")
    return builder.as_markup()

def back_kb(target):
    builder = InlineKeyboardBuilder()
    builder.button(text="[ ◀️ НАЗАД ]", callback_data=f"back_to_{target}")
    return builder.as_markup()