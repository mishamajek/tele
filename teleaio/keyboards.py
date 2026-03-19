from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder

# Монохромный стиль - только черно-белые символы

def main_kb():
    builder = InlineKeyboardBuilder()
    builder.button(text="[ РАССЫЛКА ]", callback_data="mailing")
    builder.button(text="[ АККАУНТЫ ]", callback_data="accounts")
    builder.button(text="[ ПРОФИЛЬ ]", callback_data="profile")
    builder.button(text="[ ПОДДЕРЖКА ]", callback_data="support")
    if is_admin := False:  # Это заглушка, админ определится в боте
        builder.button(text="[ АДМИН ]", callback_data="admin")
    builder.adjust(2, 2, 1)
    return builder.as_markup()

def mailing_kb():
    builder = InlineKeyboardBuilder()
    builder.button(text="[ ЗАПУСТИТЬ РАССЫЛКУ ]", callback_data="start_mailing")
    builder.button(text="[ ТЕСТОВЫЙ РЕЖИМ ]", callback_data="test_mailing")
    builder.button(text="[ НАЗАД ]", callback_data="back_main")
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
    
    builder.button(text="[ НАЗАД ]", callback_data="back_main")
    builder.adjust(1)
    return builder.as_markup()

def profile_kb(has_subscription=False):
    builder = InlineKeyboardBuilder()
    builder.button(text="[ МОИ ПОДПИСКИ ]", callback_data="my_subscriptions")
    builder.button(text="[ ИСТОРИЯ ПОКУПОК ]", callback_data="my_purchases")
    builder.button(text="[ КУПИТЬ ПОДПИСКУ ]", callback_data="buy_subscription")
    builder.button(text="[ НАЗАД ]", callback_data="back_main")
    builder.adjust(1)
    return builder.as_markup()

def subscription_kb(price):
    builder = InlineKeyboardBuilder()
    builder.button(text=f"[ ОПЛАТИТЬ {price}⭐ ]", callback_data="pay_subscription")
    if not user_has_trial:  # Заглушка
        builder.button(text="[ ПРОБНЫЙ ПЕРИОД ]", callback_data="trial_subscription")
    builder.button(text="[ НАЗАД ]", callback_data="profile")
    builder.adjust(1)
    return builder.as_markup()

def admin_kb():
    builder = InlineKeyboardBuilder()
    builder.button(text="[ СТАТИСТИКА ]", callback_data="admin_stats")
    builder.button(text="[ ДОБАВИТЬ АККАУНТ ]", callback_data="admin_add_account")
    builder.button(text="[ УПРАВЛЕНИЕ ЦЕНАМИ ]", callback_data="admin_prices")
    builder.button(text="[ УПРАВЛЕНИЕ ПОДПИСКАМИ ]", callback_data="admin_subs")
    builder.button(text="[ РАССЫЛКА ВСЕМ ]", callback_data="admin_broadcast")
    builder.button(text="[ НАЗАД ]", callback_data="back_main")
    builder.adjust(1)
    return builder.as_markup()

def admin_prices_kb():
    builder = InlineKeyboardBuilder()
    builder.button(text="[ ИЗМЕНИТЬ ЦЕНУ ПОДПИСКИ ]", callback_data="admin_edit_sub_price")
    builder.button(text="[ ИЗМЕНИТЬ ЦЕНУ АККАУНТА ]", callback_data="admin_edit_acc_price")
    builder.button(text="[ ИЗМЕНИТЬ ПРОБНЫЙ ПЕРИОД ]", callback_data="admin_edit_trial")
    builder.button(text="[ НАЗАД ]", callback_data="admin")
    builder.adjust(1)
    return builder.as_markup()

def cancel_kb():
    builder = InlineKeyboardBuilder()
    builder.button(text="[ ОТМЕНА ]", callback_data="cancel")
    return builder.as_markup()

def back_kb(target):
    builder = InlineKeyboardBuilder()
    builder.button(text="[ НАЗАД ]", callback_data=f"back_{target}")
    return builder.as_markup()

def confirm_kb(action, data):
    builder = InlineKeyboardBuilder()
    builder.button(text="[ ПОДТВЕРДИТЬ ]", callback_data=f"confirm_{action}_{data}")
    builder.button(text="[ ОТМЕНА ]", callback_data="cancel")
    builder.adjust(1)
    return builder.as_markup()