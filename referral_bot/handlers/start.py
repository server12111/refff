from aiogram import Router, Bot
from aiogram.filters import CommandStart
from aiogram.types import Message, CallbackQuery
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import IntegrityError

from database.models import User, BotSettings
from handlers.button_helper import answer_with_content, send_with_content
from keyboards.main import main_menu_kb
from config import config

router = Router()


async def _register_user(
    session: AsyncSession,
    user_id: int,
    username: str | None,
    first_name: str,
    referrer_id: int | None,
) -> tuple[User, bool, float]:
    """Returns (user, is_new, referral_reward_given)."""
    db_user = await session.get(User, user_id)
    if db_user is not None:
        db_user.username = username
        db_user.first_name = first_name
        await session.commit()
        return db_user, False, 0.0

    # New user — assign referrer only now
    valid_referrer = None
    if referrer_id and referrer_id != user_id:
        referrer = await session.get(User, referrer_id)
        if referrer:
            valid_referrer = referrer_id

    db_user = User(
        user_id=user_id,
        username=username,
        first_name=first_name,
        referrer_id=valid_referrer,
    )
    session.add(db_user)

    reward_given = 0.0
    if valid_referrer:
        referrer = await session.get(User, valid_referrer)
        if referrer:
            rr_row = await session.get(BotSettings, "referral_reward")
            reward_given = float(rr_row.value) if rr_row else config.REFERRAL_REWARD
            referrer.stars_balance += reward_given
            referrer.referrals_count += 1

    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        db_user = await session.get(User, user_id)
        return db_user, False, 0.0

    return db_user, True, reward_given


@router.message(CommandStart())
async def cmd_start(message: Message, session: AsyncSession) -> None:
    args = message.text.split(maxsplit=1)[1] if len(message.text.split()) > 1 else ""
    referrer_id = None
    if args.startswith("ref_"):
        try:
            referrer_id = int(args[4:])
        except ValueError:
            pass

    user, is_new, reward_given = await _register_user(
        session,
        message.from_user.id,
        message.from_user.username,
        message.from_user.first_name,
        referrer_id,
    )

    if is_new and user.referrer_id:
        await message.answer("👋 Добро пожаловать! Ты перешёл по реферальной ссылке.")
        bot: Bot = message.bot
        try:
            await bot.send_message(
                user.referrer_id,
                f"🎉 Вам начислено <b>{reward_given} ⭐</b> за нового реферала!",
                parse_mode="HTML",
            )
        except Exception:
            pass

    default_text = (
        "👋 <b>Добро пожаловать в SrvNkStars!</b>\n\n"
        "🌟 Зарабатывай Telegram Stars прямо здесь:\n\n"
        "• ⭐ <b>Рефералы</b> — приглашай друзей и получай звёзды за каждого\n"
        "• 📋 <b>Задания</b> — подписывайся на каналы и выполняй задачи\n"
        "• 🎮 <b>Игры</b> — испытай удачу в мини-играх\n"
        "• 🎁 <b>Бонус</b> — бесплатные звёзды каждые 24 часа\n"
        "• 💰 <b>Вывод</b> — выводи накопленное на свой Telegram\n\n"
        "Выбери раздел ниже 👇"
    )
    await send_with_content(message, session, "menu:main", default_text, main_menu_kb())


@router.callback_query(lambda c: c.data == "menu:main")
async def cb_main_menu(callback: CallbackQuery, session: AsyncSession) -> None:
    default_text = (
        "👋 <b>Главное меню</b>\n\n"
        "🌟 Зарабатывай Telegram Stars прямо здесь:\n\n"
        "• ⭐ <b>Рефералы</b> — приглашай друзей и получай звёзды за каждого\n"
        "• 📋 <b>Задания</b> — подписывайся на каналы и выполняй задачи\n"
        "• 🎮 <b>Игры</b> — испытай удачу в мини-играх\n"
        "• 🎁 <b>Бонус</b> — бесплатные звёзды каждые 24 часа\n"
        "• 💰 <b>Вывод</b> — выводи накопленное на свой Telegram\n\n"
        "Выбери раздел ниже 👇"
    )
    await answer_with_content(callback, session, "menu:main", default_text, main_menu_kb())
    await callback.answer()
