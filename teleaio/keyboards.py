from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder

# Монохромный стиль - только черно-белые символы

def main_kb():
    builder = InlineKeyboardBuilder()
    builder.button(text="[ РАССЫЛКА ]", callback_data="mailing")
    builder.button(text="[ АККАУНТЫ ]", callback_data="accounts")
    builder.button(text="[ ПРОФИЛЬ ]", callback_data="profile")
    builder.button(text="[ ПОМОЩЬ ]", callback_data="help")
    builder.adjust(2, 2)
    return builder.as_markup()

def mailing_kb(has_accounts=False):
    builder = InlineKeyboardBuilder()
    if has_accounts:
        builder.button(text="[ НОВАЯ РАССЫЛКА ]", callback_data="new_mailing")
        builder.button(text="[ МОИ РАССЫЛКИ ]", callback_data="my_mailings")
        builder.button(text="[ УПРАВЛЕНИЕ АККАУНТАМИ ]", callback_data="my_accounts")
    else:
        builder.button(text="[ + ДОБАВИТЬ АККАУНТ ]", callback_data="add_account")
    builder.button(text="[ НАЗАД ]", callback_data="back_to_main")
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
    builder.button(text="[ НАЗАД ]", callback_data="back_to_mailing")
    builder.adjust(1)
    return builder.as_markup()

def account_info_kb(account_id):
    builder = InlineKeyboardBuilder()
    builder.button(text="[ УДАЛИТЬ ]", callback_data=f"delete_account_{account_id}")
    builder.button(text="[ НАЗАД ]", callback_data="back_to_my_accounts")
    builder.adjust(1)
    return builder.as_markup()

def accounts_kb(accounts, page=0, per_page=5):
    builder = InlineKeyboardBuilder()
    
    start = page * per_page
    end = start + per_page
    page_accounts = accounts[start:end]
    
    for acc in page_accounts:
        builder.button(
            text=f"[ +{acc['phone']} ] - {acc['price']}⭐", 
            callback_data=f"buy_account_{acc['id']}"
        )
    
    # Пагинация
    nav_buttons = []
    if page > 0:
        nav_buttons.append(InlineKeyboardButton(text="<", callback_data=f"accounts_page_{page-1}"))
    nav_buttons.append(InlineKeyboardButton(text=f"-{page+1}-", callback_data="ignore"))
    if end < len(accounts):
        nav_buttons.append(InlineKeyboardButton(text=">", callback_data=f"accounts_page_{page+1}"))
    
    if nav_buttons:
        builder.row(*nav_buttons)
    
    builder.button(text="[ НАЗАД ]", callback_data="back_to_main")
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
    for m in mailings[:5]:
        status = "✅" if m['status'] == 'completed' else "⏳" if m['status'] == 'running' else "⏸️"
        builder.button(
            text=f"{status} {m['started'][:16] if m['started'] else 'Новая'}", 
            callback_data=f"mailing_info_{m['id']}"
        )
    builder.button(text="[ НАЗАД ]", callback_data="back_to_mailing")
    builder.adjust(1)
    return builder.as_markup()

def mailing_info_kb(mailing_id):
    builder = InlineKeyboardBuilder()
    builder.button(text="[ 🔄 ОБНОВИТЬ ]", callback_data=f"mailing_refresh_{mailing_id}")
    builder.button(text="[ ❌ УДАЛИТЬ ]", callback_data=f"mailing_delete_{mailing_id}")
    builder.button(text="[ ⏸️ ПАУЗА ]", callback_data=f"mailing_pause_{mailing_id}")
    builder.button(text="[ ▶️ ВОЗОБНОВИТЬ ]", callback_data=f"mailing_resume_{mailing_id}")
    builder.button(text="[ ◀️ НАЗАД ]", callback_data="back_to_my_mailings")
    builder.adjust(1)
    return builder.as_markup()

def admin_kb():
    builder = InlineKeyboardBuilder()
    builder.button(text="[ СТАТИСТИКА ]", callback_data="admin_stats")
    builder.button(text="[ ДОБАВИТЬ АККАУНТ ]", callback_data="admin_add_account")
    builder.button(text="[ УПРАВЛЕНИЕ ЦЕНАМИ ]", callback_data="admin_prices")
    builder.button(text="[ РАССЫЛКА ВСЕМ ]", callback_data="admin_broadcast")
    builder.button(text="[ НАЗАД ]", callback_data="back_to_main")
    builder.adjust(1)
    return builder.as_markup()

def admin_prices_kb():
    builder = InlineKeyboardBuilder()
    builder.button(text="[ ЦЕНА ПОДПИСКИ ]", callback_data="admin_edit_sub_price")
    builder.button(text="[ ЦЕНА АККАУНТА ]", callback_data="admin_edit_acc_price")
    builder.button(text="[ ПРОБНЫЙ ПЕРИОД ]", callback_data="admin_edit_trial")
    builder.button(text="[ ЛИМИТЫ РАССЫЛКИ ]", callback_data="admin_edit_limits")
    builder.button(text="[ НАЗАД ]", callback_data="back_to_admin")
    builder.adjust(1)
    return builder.as_markup()

def cancel_only_kb():
    builder = InlineKeyboardBuilder()
    builder.button(text="[ ОТМЕНА ]", callback_data="cancel_operation")
    return builder.as_markup()

def back_kb(target):
    builder = InlineKeyboardBuilder()
    builder.button(text="[ НАЗАД ]", callback_data=f"back_to_{target}")
    return builder.as_markup()

def confirm_kb(action, data):
    builder = InlineKeyboardBuilder()
    builder.button(text="[ ПОДТВЕРДИТЬ ]", callback_data=f"confirm_{action}_{data}")
    builder.button(text="[ ОТМЕНА ]", callback_data="cancel_operation")
    builder.adjust(1)
    return builder.as_markup()