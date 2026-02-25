from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder

GAME_TYPES = ["football", "basketball", "bowling", "dice", "slots"]

GAME_LABELS = {
    "football":   "⚽ Футбол",
    "basketball": "🏀 Баскетбол",
    "bowling":    "🎳 Боулинг",
    "dice":       "🎲 Кубики",
    "slots":      "🎰 Слоты",
}


def games_menu_kb(configs: dict) -> InlineKeyboardMarkup:
    """configs: {game_type: {"enabled": bool, "min_bet": float, "coeff_label": str}}"""
    builder = InlineKeyboardBuilder()
    for game in GAME_TYPES:
        cfg = configs.get(game, {})
        if cfg.get("enabled"):
            min_bet = cfg.get("min_bet", 1.0)
            coeff_label = cfg.get("coeff_label", "")
            builder.row(InlineKeyboardButton(
                text=f"{GAME_LABELS[game]} — от {min_bet:.0f} ⭐ | {coeff_label}",
                callback_data=f"game:play:{game}",
            ))
    builder.row(InlineKeyboardButton(text="◀️ Назад", callback_data="menu:main"))
    return builder.as_markup()


def dice_side_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="📈 Больше 3", callback_data="game:dice:high"),
        InlineKeyboardButton(text="📉 Меньше 4", callback_data="game:dice:low"),
    )
    builder.row(InlineKeyboardButton(text="❌ Отмена", callback_data="menu:games"))
    return builder.as_markup()


def game_result_kb(game_type: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="🔁 Сыграть ещё раз", callback_data=f"game:play:{game_type}"))
    builder.row(InlineKeyboardButton(text="🎮 К играм", callback_data="menu:games"))
    return builder.as_markup()


def game_cancel_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="❌ Отмена", callback_data="menu:games")]]
    )
