from aiogram import Router
from aiogram.types import CallbackQuery
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

from database.models import User
from handlers.button_helper import answer_with_content
from keyboards.main import back_to_menu_kb

router = Router()

MEDALS = {1: "🥇", 2: "🥈", 3: "🥉"}
NUMBERS = {4: "4️⃣", 5: "5️⃣", 6: "6️⃣", 7: "7️⃣", 8: "8️⃣", 9: "9️⃣", 10: "🔟"}


@router.callback_query(lambda c: c.data == "menu:top")
async def cb_top(callback: CallbackQuery, session: AsyncSession, db_user: User) -> None:
    # Top-10 via window function — одним запросом, эффективно на большой БД
    top_rows = (await session.execute(text("""
        SELECT user_id, username, referrals_count, stars_balance
        FROM users
        ORDER BY referrals_count DESC, stars_balance DESC, created_at ASC
        LIMIT 10
    """))).fetchall()

    # Ранг текущего пользователя: считаем тех, кто "лучше"
    user_rank = (await session.execute(text("""
        SELECT COUNT(*) + 1
        FROM users
        WHERE referrals_count > :rc
           OR (referrals_count = :rc AND stars_balance > :sb)
           OR (referrals_count = :rc AND stars_balance = :sb AND created_at < :ca)
    """), {
        "rc": db_user.referrals_count,
        "sb": db_user.stars_balance,
        "ca": db_user.created_at,
    })).scalar()

    lines = ["🏆 <b>Топ пользователей</b>\n"]

    for pos, row in enumerate(top_rows, start=1):
        uid, username, referrals, stars = row
        display = f"@{username}" if username else f"ID {uid}"

        if pos <= 3:
            medal = MEDALS[pos]
            lines.append(
                f"{medal} {pos} место — {display}\n"
                f"👥 Рефералы: {referrals}\n"
                f"⭐ Заработано: {stars:.0f}\n"
            )
        else:
            num = NUMBERS.get(pos, f"{pos}.")
            lines.append(f"{num} {display} — 👥 {referrals} | ⭐ {stars:.0f}")

    u_display = f"@{db_user.username}" if db_user.username else f"ID {db_user.user_id}"
    lines.append(
        f"\n📍 <b>Ваше место в рейтинге:</b>\n"
        f"Вы на {user_rank} месте\n"
        f"👥 Рефералы: {db_user.referrals_count}\n"
        f"⭐ Заработано: {db_user.stars_balance:.0f}"
    )

    await answer_with_content(callback, session, "menu:top", "\n".join(lines), back_to_menu_kb())
    await callback.answer()
