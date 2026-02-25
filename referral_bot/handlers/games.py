from datetime import date, datetime

from aiogram import Router, Bot
from aiogram.types import CallbackQuery, Message
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from database.models import User, GameSession, BotSettings
from handlers.button_helper import answer_with_content, safe_edit
from keyboards.games import (
    games_menu_kb, dice_side_kb, game_result_kb, game_cancel_kb,
    GAME_TYPES, GAME_LABELS,
)

router = Router()

GAME_EMOJIS = {
    "football":   "⚽",
    "basketball": "🏀",
    "bowling":    "🎳",
    "dice":       "🎲",
    "slots":      "🎰",
}

GAME_DEFAULTS = {
    "football":   {"coeff": 2.5,  "min_bet": 1.0, "daily_limit": 0},
    "basketball": {"coeff": 1.25, "min_bet": 1.0, "daily_limit": 0},
    "bowling":    {"coeff": 3.0,  "min_bet": 1.0, "daily_limit": 0},
    "dice":       {"coeff": 1.5,  "min_bet": 1.0, "daily_limit": 0},
    "slots":      {"coeff1": 6.0, "coeff2": 2.0, "min_bet": 1.0, "daily_limit": 0},
}


class GameStates(StatesGroup):
    enter_bet = State()
    choose_dice_side = State()


# ─── Helpers ──────────────────────────────────────────────────────────────────

async def _get_float(session: AsyncSession, key: str, default: float) -> float:
    row = await session.get(BotSettings, key)
    if row:
        try:
            return float(row.value)
        except ValueError:
            pass
    return default


async def _get_int(session: AsyncSession, key: str, default: int) -> int:
    row = await session.get(BotSettings, key)
    if row:
        try:
            return int(row.value)
        except ValueError:
            pass
    return default


async def _is_enabled(session: AsyncSession, game: str) -> bool:
    row = await session.get(BotSettings, f"game_{game}_enabled")
    return (row.value == "1") if row else True


async def _get_daily_count(session: AsyncSession, user_id: int, game: str) -> int:
    today_start = datetime.combine(date.today(), datetime.min.time())
    result = await session.execute(
        select(func.count(GameSession.id)).where(
            GameSession.user_id == user_id,
            GameSession.game_type == game,
            GameSession.played_at >= today_start,
        )
    )
    return result.scalar() or 0


async def _load_games_config(session: AsyncSession) -> dict:
    configs = {}
    for game in GAME_TYPES:
        enabled_row = await session.get(BotSettings, f"game_{game}_enabled")
        min_bet_row = await session.get(BotSettings, f"game_{game}_min_bet")
        cfg = {
            "enabled": (enabled_row.value == "1") if enabled_row else True,
            "min_bet": float(min_bet_row.value) if min_bet_row else 1.0,
        }
        if game == "slots":
            c1 = await _get_float(session, "game_slots_coeff1", 6.0)
            c2 = await _get_float(session, "game_slots_coeff2", 2.0)
            cfg["coeff_label"] = f"x{c2:.4g}–x{c1:.4g}"
        else:
            default = GAME_DEFAULTS[game]["coeff"]
            c = await _get_float(session, f"game_{game}_coeff", default)
            cfg["coeff_label"] = f"x{c:.4g}"
        configs[game] = cfg
    return configs


async def _execute_game(
    bot: Bot,
    chat_id: int,
    session: AsyncSession,
    db_user: User,
    game_type: str,
    bet: float,
    dice_side: str | None = None,
) -> tuple[bool, float, int]:
    """Send dice, evaluate result, update balance and record session.
    Returns (won, payout, dice_value). Bet must be deducted before calling."""
    dice_msg = await bot.send_dice(chat_id=chat_id, emoji=GAME_EMOJIS[game_type])
    value = dice_msg.dice.value

    won = False
    payout = 0.0

    if game_type == "football":
        coeff = await _get_float(session, "game_football_coeff", 3.0)
        if value == 5:
            won, payout = True, round(bet * coeff, 2)

    elif game_type == "basketball":
        coeff = await _get_float(session, "game_basketball_coeff", 2.5)
        if value in (4, 5):
            won, payout = True, round(bet * coeff, 2)

    elif game_type == "bowling":
        coeff = await _get_float(session, "game_bowling_coeff", 4.0)
        if value == 6:
            won, payout = True, round(bet * coeff, 2)

    elif game_type == "dice":
        coeff = await _get_float(session, "game_dice_coeff", 1.9)
        if (dice_side == "high" and value > 3) or (dice_side == "low" and value < 4):
            won, payout = True, round(bet * coeff, 2)

    elif game_type == "slots":
        coeff1 = await _get_float(session, "game_slots_coeff1", 5.0)
        coeff2 = await _get_float(session, "game_slots_coeff2", 2.0)
        if 1 <= value <= 3:
            won, payout = True, round(bet * coeff1, 2)
        elif 4 <= value <= 10:
            won, payout = True, round(bet * coeff2, 2)

    if won:
        db_user.stars_balance += payout

    session.add(GameSession(
        user_id=db_user.user_id,
        game_type=game_type,
        bet=bet,
        result="win" if won else "lose",
        payout=payout,
    ))
    await session.commit()

    return won, payout, value


def _result_text(
    game_type: str,
    won: bool,
    bet: float,
    payout: float,
    value: int,
    new_balance: float,
    dice_side: str | None = None,
) -> str:
    label = GAME_LABELS[game_type]

    desc_lines = {
        "football":   "⚽ Гол!" if won else "⚽ Промах.",
        "basketball": "🏀 Попадание!" if won else "🏀 Мимо.",
        "bowling":    "🎳 Страйк!" if won else "🎳 Не страйк.",
        "dice":       f"🎲 Выпало: <b>{value}</b> | {'📈 Больше 3' if dice_side == 'high' else '📉 Меньше 4'}",
        "slots":      f"🎰 Значение: <b>{value}</b>",
    }

    if won:
        profit = round(payout - bet, 2)
        result_line = f"🎉 <b>Выигрыш! +{payout:.2f} ⭐</b>"
        extra = f"Прибыль: +{profit:.2f} ⭐"
    else:
        result_line = f"😞 <b>Проигрыш. -{bet:.2f} ⭐</b>"
        extra = ""

    parts = [
        f"<b>{label}</b>",
        "",
        desc_lines.get(game_type, ""),
        result_line,
    ]
    if extra:
        parts.append(extra)
    parts.append(f"\n💰 Баланс: <b>{new_balance:.2f} ⭐</b>")
    return "\n".join(parts)


# ─── Games menu ───────────────────────────────────────────────────────────────

@router.callback_query(lambda c: c.data == "menu:games")
async def cb_games_menu(
    callback: CallbackQuery,
    session: AsyncSession,
    db_user: User,
    state: FSMContext,
) -> None:
    # Refund bet if user cancels during dice-side selection
    fsm_state = await state.get_state()
    if fsm_state == GameStates.choose_dice_side:
        data = await state.get_data()
        bet = data.get("bet", 0.0)
        if bet:
            db_user.stars_balance += bet
            await session.commit()
    await state.clear()

    configs = await _load_games_config(session)
    has_any = any(cfg["enabled"] for cfg in configs.values())

    if has_any:
        default_text = (
            f"🎮 <b>Игры</b>\n\n"
            f"Твой баланс: <b>{db_user.stars_balance:.2f} ⭐</b>\n\n"
            f"Выбери игру:"
        )
    else:
        default_text = "🎮 <b>Игры</b>\n\nИгры временно недоступны."

    await answer_with_content(callback, session, "menu:games", default_text, games_menu_kb(configs))
    await callback.answer()


# ─── Select game → enter bet ──────────────────────────────────────────────────

@router.callback_query(lambda c: c.data and c.data.startswith("game:play:"))
async def cb_game_play(
    callback: CallbackQuery,
    session: AsyncSession,
    db_user: User,
    state: FSMContext,
) -> None:
    await state.clear()
    game_type = callback.data.split(":")[2]

    if game_type not in GAME_TYPES:
        await callback.answer("Неизвестная игра.", show_alert=True)
        return

    if not await _is_enabled(session, game_type):
        await callback.answer("Эта игра временно отключена.", show_alert=True)
        return

    daily_limit = await _get_int(session, f"game_{game_type}_daily_limit", 0)
    if daily_limit > 0:
        daily_count = await _get_daily_count(session, db_user.user_id, game_type)
        if daily_count >= daily_limit:
            await callback.answer(
                f"⛔ Достигнут дневной лимит ({daily_limit} игр). Попробуй завтра.",
                show_alert=True,
            )
            return

    min_bet = await _get_float(session, f"game_{game_type}_min_bet", 1.0)

    if db_user.stars_balance < min_bet:
        await callback.answer(
            f"❌ Недостаточно звёзд. Минимальная ставка: {min_bet:.0f} ⭐",
            show_alert=True,
        )
        return

    await state.set_state(GameStates.enter_bet)
    await state.update_data(game_type=game_type)

    await safe_edit(
        callback,
        f"<b>{GAME_LABELS[game_type]}</b>\n\n"
        f"💰 Твой баланс: <b>{db_user.stars_balance:.2f} ⭐</b>\n"
        f"Минимальная ставка: <b>{min_bet:.0f} ⭐</b>\n\n"
        f"Введи сумму ставки:",
        game_cancel_kb(),
    )
    await callback.answer()


# ─── Bet entered ──────────────────────────────────────────────────────────────

@router.message(GameStates.enter_bet)
async def msg_bet_enter(
    message: Message,
    session: AsyncSession,
    db_user: User,
    state: FSMContext,
) -> None:
    data = await state.get_data()
    game_type = data["game_type"]

    try:
        bet = float(message.text.strip().replace(",", "."))
    except ValueError:
        await message.answer(
            "❌ Введи число — сумму ставки:",
            reply_markup=game_cancel_kb(),
        )
        return

    if bet <= 0:
        await message.answer("❌ Ставка должна быть больше нуля:", reply_markup=game_cancel_kb())
        return

    min_bet = await _get_float(session, f"game_{game_type}_min_bet", 1.0)
    if bet < min_bet:
        await message.answer(
            f"❌ Минимальная ставка: <b>{min_bet:.0f} ⭐</b>",
            parse_mode="HTML",
            reply_markup=game_cancel_kb(),
        )
        return

    if db_user.stars_balance < bet:
        await message.answer(
            f"❌ Недостаточно звёзд. Баланс: <b>{db_user.stars_balance:.2f} ⭐</b>",
            parse_mode="HTML",
            reply_markup=game_cancel_kb(),
        )
        return

    # Deduct bet before game starts
    db_user.stars_balance -= bet
    await session.commit()

    # Dice needs side selection first
    if game_type == "dice":
        await state.set_state(GameStates.choose_dice_side)
        await state.update_data(bet=bet)
        await message.answer(
            f"🎲 <b>Кубики</b>\n\n"
            f"Ставка: <b>{bet:.0f} ⭐</b>\n\n"
            f"Выбери условие победы:",
            parse_mode="HTML",
            reply_markup=dice_side_kb(),
        )
        return

    await state.clear()

    try:
        won, payout, value = await _execute_game(
            bot=message.bot,
            chat_id=message.chat.id,
            session=session,
            db_user=db_user,
            game_type=game_type,
            bet=bet,
        )
    except Exception:
        # Refund on send error
        db_user.stars_balance += bet
        await session.commit()
        await message.answer("⚠️ Ошибка при отправке игры. Ставка возвращена.", reply_markup=game_cancel_kb())
        return

    await message.answer(
        _result_text(game_type, won, bet, payout, value, db_user.stars_balance),
        parse_mode="HTML",
        reply_markup=game_result_kb(game_type),
    )


# ─── Dice: choose side ────────────────────────────────────────────────────────

@router.callback_query(GameStates.choose_dice_side, lambda c: c.data and c.data.startswith("game:dice:"))
async def cb_dice_side(
    callback: CallbackQuery,
    session: AsyncSession,
    db_user: User,
    state: FSMContext,
) -> None:
    dice_side = callback.data.split(":")[2]  # "high" or "low"
    data = await state.get_data()
    bet = data["bet"]
    await state.clear()

    try:
        won, payout, value = await _execute_game(
            bot=callback.bot,
            chat_id=callback.message.chat.id,
            session=session,
            db_user=db_user,
            game_type="dice",
            bet=bet,
            dice_side=dice_side,
        )
    except Exception:
        db_user.stars_balance += bet
        await session.commit()
        await callback.message.answer("⚠️ Ошибка при отправке игры. Ставка возвращена.", reply_markup=game_cancel_kb())
        await callback.answer()
        return

    await callback.message.answer(
        _result_text("dice", won, bet, payout, value, db_user.stars_balance, dice_side),
        parse_mode="HTML",
        reply_markup=game_result_kb("dice"),
    )
    await callback.answer()
