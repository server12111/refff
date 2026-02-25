from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder


def main_menu_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="⭐ Заработать звёзды", callback_data="menu:earn"))
    builder.row(InlineKeyboardButton(text="👥 Мои рефералы", callback_data="menu:referrals"))
    builder.row(
        InlineKeyboardButton(text="🎁 Бонус", callback_data="menu:bonus"),
        InlineKeyboardButton(text="👤 Профиль", callback_data="menu:profile"),
    )
    builder.row(InlineKeyboardButton(text="📋 Задания", callback_data="menu:tasks"))
    builder.row(
        InlineKeyboardButton(text="🏆 Топ", callback_data="menu:top"),
        InlineKeyboardButton(text="🎮 Игры", callback_data="menu:games"),
    )
    builder.row(InlineKeyboardButton(text="💰 Вывод", callback_data="menu:withdraw"))
    builder.row(InlineKeyboardButton(text="ℹ️ Как это работает", callback_data="menu:how"))
    return builder.as_markup()


def back_to_menu_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="◀️ Назад", callback_data="menu:main")]]
    )


def profile_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="🎟 Ввести промокод", callback_data="promo:enter"))
    builder.row(InlineKeyboardButton(text="◀️ Назад", callback_data="menu:main"))
    return builder.as_markup()


def tasks_list_kb(tasks: list, completed_ids: set) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for task in tasks:
        done = task.id in completed_ids
        prefix = "✅ " if done else ""
        builder.row(InlineKeyboardButton(
            text=f"{prefix}{task.title} (+{task.reward} ⭐)",
            callback_data=f"task:view:{task.id}",
        ))
    builder.row(InlineKeyboardButton(text="◀️ Назад", callback_data="menu:main"))
    return builder.as_markup()


def task_detail_kb(task_id: int, task_type: str, channel_id: str | None, completed: bool) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    if not completed:
        if task_type == "subscribe" and channel_id:
            builder.row(InlineKeyboardButton(
                text="📢 Подписаться",
                url=f"https://t.me/{channel_id.lstrip('@').lstrip('-100')}",
            ))
            builder.row(InlineKeyboardButton(text="🔍 Проверить подписку", callback_data=f"task:check:{task_id}"))
        else:
            builder.row(InlineKeyboardButton(text="✅ Проверить", callback_data=f"task:check:{task_id}"))
    builder.row(InlineKeyboardButton(text="◀️ Назад", callback_data="menu:tasks"))
    return builder.as_markup()


def back_to_tasks_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="◀️ К заданиям", callback_data="menu:tasks")]]
    )
