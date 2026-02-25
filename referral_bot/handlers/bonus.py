import random
from datetime import datetime, timedelta

from aiogram import Router
from aiogram.types import CallbackQuery
from sqlalchemy.ext.asyncio import AsyncSession

from database.models import User, BotSettings
from handlers.button_helper import answer_with_content
from keyboards.main import back_to_menu_kb
from config import config

router = Router()


async def _get_float_setting(session: AsyncSession, key: str, default: float) -> float:
    row = await session.get(BotSettings, key)
    if row:
        try:
            return float(row.value)
        except ValueError:
            pass
    return default


@router.callback_query(lambda c: c.data == "menu:bonus")
async def cb_bonus(callback: CallbackQuery, session: AsyncSession, db_user: User) -> None:
    cooldown_row = await session.get(BotSettings, "bonus_cooldown_hours")
    cooldown_hours = int(float(cooldown_row.value)) if cooldown_row else config.BONUS_COOLDOWN_HOURS

    now = datetime.utcnow()

    if db_user.last_bonus_at:
        next_bonus = db_user.last_bonus_at + timedelta(hours=cooldown_hours)
        if now < next_bonus:
            remaining = next_bonus - now
            hours, remainder = divmod(int(remaining.total_seconds()), 3600)
            minutes, seconds = divmod(remainder, 60)
            cooldown_text = (
                f"⏳ Бонус уже получен.\n\n"
                f"Следующий бонус будет доступен через: <b>{hours:02d}:{minutes:02d}:{seconds:02d}</b>"
            )
            await answer_with_content(callback, session, "menu:bonus", cooldown_text, back_to_menu_kb())
            await callback.answer()
            return

    bonus_min = await _get_float_setting(session, "bonus_min", config.BONUS_MIN)
    bonus_max = await _get_float_setting(session, "bonus_max", config.BONUS_MAX)
    amount = round(random.uniform(bonus_min, bonus_max), 2)

    db_user.stars_balance += amount
    db_user.last_bonus_at = now
    await session.commit()

    bonus_text = (
        f"🎁 Вам начислено <b>{amount} ⭐</b> бонуса!\n\n"
        f"Текущий баланс: <b>{db_user.stars_balance:.2f} ⭐</b>"
    )
    await answer_with_content(callback, session, "menu:bonus", bonus_text, back_to_menu_kb())
    await callback.answer(f"+{amount} ⭐")
