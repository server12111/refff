from datetime import datetime
from aiogram import Router, Bot
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from database.models import User, PromoCode, PromoUse, Withdrawal, BotSettings, Task, TaskCompletion
from handlers.withdraw import build_withdrawal_msg
from database.engine import set_setting, get_button_content, set_button_photo, set_button_text
from keyboards.admin import (
    admin_main_kb, admin_settings_kb, promo_list_kb,
    promo_actions_kb, promo_reward_type_kb, admin_back_kb,
    task_management_kb, task_type_kb, task_list_admin_kb, task_actions_kb,
    games_list_kb, game_detail_kb,
    BUTTON_KEYS, button_content_list_kb, button_edit_kb,
)
from config import config

router = Router()


# ─── FSM States ──────────────────────────────────────────────────────────────

class AdminPromoStates(StatesGroup):
    code = State()
    reward_type = State()
    reward_fixed = State()
    reward_min = State()
    reward_max = State()
    usage_limit = State()


class AdminCreditStates(StatesGroup):
    user_id = State()
    amount = State()


class AdminSettingsStates(StatesGroup):
    referral_reward = State()
    bonus_cooldown = State()
    bonus_min = State()
    bonus_max = State()
    payments_channel_id = State()
    payments_channel_url = State()


class AdminBroadcastStates(StatesGroup):
    text = State()


class AdminTaskStates(StatesGroup):
    task_type = State()
    title = State()
    description = State()
    reward = State()
    channel_id = State()
    target_value = State()


class AdminGameStates(StatesGroup):
    set_coeff = State()
    set_coeff1 = State()
    set_coeff2 = State()
    set_min_bet = State()
    set_daily_limit = State()


class AdminButtonContentStates(StatesGroup):
    set_photo = State()
    set_text = State()


# ─── Guard ───────────────────────────────────────────────────────────────────

def is_admin(user_id: int) -> bool:
    return user_id in config.ADMIN_IDS


# ─── Entry ───────────────────────────────────────────────────────────────────

@router.message(Command("admin"))
async def cmd_admin(message: Message) -> None:
    if not is_admin(message.from_user.id):
        return
    await message.answer("🛠 <b>Админ-панель</b>", parse_mode="HTML", reply_markup=admin_main_kb())


@router.callback_query(lambda c: c.data == "admin:main")
async def cb_admin_main(callback: CallbackQuery) -> None:
    if not is_admin(callback.from_user.id):
        return await callback.answer("Нет доступа.", show_alert=True)
    await callback.message.edit_text("🛠 <b>Админ-панель</b>", parse_mode="HTML", reply_markup=admin_main_kb())
    await callback.answer()


# ─── Stats ───────────────────────────────────────────────────────────────────

@router.callback_query(lambda c: c.data == "admin:stats")
async def cb_stats(callback: CallbackQuery, session: AsyncSession) -> None:
    if not is_admin(callback.from_user.id):
        return await callback.answer("Нет доступа.", show_alert=True)

    total_users = (await session.execute(select(func.count(User.user_id)))).scalar()
    total_pending = (await session.execute(
        select(func.count(Withdrawal.id)).where(Withdrawal.status == "pending")
    )).scalar()
    total_approved = (await session.execute(
        select(func.sum(Withdrawal.amount)).where(Withdrawal.status == "approved")
    )).scalar() or 0

    await callback.message.edit_text(
        f"📊 <b>Статистика</b>\n\n"
        f"👥 Пользователей: <b>{total_users}</b>\n"
        f"⏳ Заявок в ожидании: <b>{total_pending}</b>\n"
        f"✅ Выведено всего: <b>{total_approved:.2f} ⭐</b>",
        parse_mode="HTML",
        reply_markup=admin_back_kb(),
    )
    await callback.answer()


# ─── Promo: Add ──────────────────────────────────────────────────────────────

@router.callback_query(lambda c: c.data == "admin:add_promo")
async def cb_add_promo(callback: CallbackQuery, state: FSMContext) -> None:
    if not is_admin(callback.from_user.id):
        return await callback.answer("Нет доступа.", show_alert=True)
    await state.set_state(AdminPromoStates.code)
    await callback.message.edit_text("🎟 Введи код промокода (латиница, без пробелов):")
    await callback.answer()


@router.message(AdminPromoStates.code)
async def msg_promo_code(message: Message, state: FSMContext, session: AsyncSession) -> None:
    code = message.text.strip().upper()
    if " " in code:
        await message.answer("❌ Код не должен содержать пробелы. Попробуй снова:")
        return
    existing = (await session.execute(select(PromoCode).where(PromoCode.code == code))).scalar_one_or_none()
    if existing:
        await message.answer("❌ Такой код уже существует. Введи другой:")
        return
    await state.update_data(code=code)
    await state.set_state(AdminPromoStates.reward_type)
    await message.answer("Выбери тип награды:", reply_markup=promo_reward_type_kb())


@router.callback_query(lambda c: c.data in ("promo_type:fixed", "promo_type:random"))
async def cb_promo_type(callback: CallbackQuery, state: FSMContext) -> None:
    is_random = callback.data == "promo_type:random"
    await state.update_data(is_random=is_random)
    if is_random:
        await state.set_state(AdminPromoStates.reward_min)
        await callback.message.edit_text("Введи минимальную награду (число):")
    else:
        await state.set_state(AdminPromoStates.reward_fixed)
        await callback.message.edit_text("Введи фиксированную награду (число):")
    await callback.answer()


@router.message(AdminPromoStates.reward_fixed)
async def msg_promo_fixed(message: Message, state: FSMContext) -> None:
    try:
        reward = float(message.text.strip().replace(",", "."))
    except ValueError:
        await message.answer("❌ Введи число, например: 5 или 2.5")
        return
    await state.update_data(reward=reward)
    await state.set_state(AdminPromoStates.usage_limit)
    await message.answer("Лимит использований (0 = безлимитный):")


@router.message(AdminPromoStates.reward_min)
async def msg_promo_min(message: Message, state: FSMContext) -> None:
    try:
        reward_min = float(message.text.strip().replace(",", "."))
    except ValueError:
        await message.answer("❌ Введи число:")
        return
    await state.update_data(reward_min=reward_min)
    await state.set_state(AdminPromoStates.reward_max)
    await message.answer("Введи максимальную награду:")


@router.message(AdminPromoStates.reward_max)
async def msg_promo_max(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    try:
        reward_max = float(message.text.strip().replace(",", "."))
    except ValueError:
        await message.answer("❌ Введи число:")
        return
    if reward_max <= data["reward_min"]:
        await message.answer("❌ Максимум должен быть больше минимума:")
        return
    await state.update_data(reward_max=reward_max, reward=0.0)
    await state.set_state(AdminPromoStates.usage_limit)
    await message.answer("Лимит использований (0 = безлимитный):")


@router.message(AdminPromoStates.usage_limit)
async def msg_promo_limit(message: Message, state: FSMContext, session: AsyncSession) -> None:
    try:
        limit_raw = int(message.text.strip())
    except ValueError:
        await message.answer("❌ Введи целое число:")
        return
    data = await state.get_data()
    await state.clear()

    promo = PromoCode(
        code=data["code"],
        reward=data.get("reward", 0.0),
        is_random=data.get("is_random", False),
        reward_min=data.get("reward_min"),
        reward_max=data.get("reward_max"),
        usage_limit=limit_raw if limit_raw > 0 else None,
    )
    session.add(promo)
    await session.commit()

    reward_desc = (
        f"{data.get('reward_min')}–{data.get('reward_max')} ⭐ (случайно)"
        if data.get("is_random")
        else f"{data.get('reward', 0):.2f} ⭐"
    )
    limit_desc = str(limit_raw) if limit_raw > 0 else "безлимитный"

    await message.answer(
        f"✅ Промокод создан!\n\n"
        f"Код: <code>{promo.code}</code>\n"
        f"Награда: {reward_desc}\n"
        f"Лимит: {limit_desc}",
        parse_mode="HTML",
        reply_markup=admin_main_kb(),
    )


# ─── Promo: List & Actions ───────────────────────────────────────────────────

@router.callback_query(lambda c: c.data == "admin:list_promos")
async def cb_list_promos(callback: CallbackQuery, session: AsyncSession) -> None:
    if not is_admin(callback.from_user.id):
        return await callback.answer("Нет доступа.", show_alert=True)
    promos = (await session.execute(select(PromoCode).order_by(PromoCode.created_at.desc()))).scalars().all()
    if not promos:
        await callback.message.edit_text("Промокодов нет.", reply_markup=admin_back_kb())
        await callback.answer()
        return
    await callback.message.edit_text("🎟 <b>Список промокодов:</b>", parse_mode="HTML", reply_markup=promo_list_kb(promos))
    await callback.answer()


@router.callback_query(lambda c: c.data and c.data.startswith("admin:promo_info:"))
async def cb_promo_info(callback: CallbackQuery, session: AsyncSession) -> None:
    if not is_admin(callback.from_user.id):
        return await callback.answer("Нет доступа.", show_alert=True)
    promo_id = int(callback.data.split(":")[2])
    promo = await session.get(PromoCode, promo_id)
    if not promo:
        await callback.answer("Промокод не найден.", show_alert=True)
        return

    reward_desc = (
        f"{promo.reward_min}–{promo.reward_max} ⭐ (случайно)"
        if promo.is_random
        else f"{promo.reward:.2f} ⭐"
    )
    limit_desc = str(promo.usage_limit) if promo.usage_limit else "безлимитный"
    status = "✅ Активен" if promo.is_active else "❌ Неактивен"

    await callback.message.edit_text(
        f"🎟 <b>{promo.code}</b>\n\n"
        f"Статус: {status}\n"
        f"Награда: {reward_desc}\n"
        f"Лимит: {limit_desc}\n"
        f"Использований: {promo.usage_count}",
        parse_mode="HTML",
        reply_markup=promo_actions_kb(promo.id, promo.is_active),
    )
    await callback.answer()


@router.callback_query(lambda c: c.data and c.data.startswith("admin:promo_toggle:"))
async def cb_promo_toggle(callback: CallbackQuery, session: AsyncSession) -> None:
    if not is_admin(callback.from_user.id):
        return await callback.answer("Нет доступа.", show_alert=True)
    promo_id = int(callback.data.split(":")[2])
    promo = await session.get(PromoCode, promo_id)
    if promo:
        promo.is_active = not promo.is_active
        await session.commit()
        await callback.answer("Статус изменён.")
        await callback.message.edit_reply_markup(reply_markup=promo_actions_kb(promo.id, promo.is_active))


@router.callback_query(lambda c: c.data and c.data.startswith("admin:promo_delete:"))
async def cb_promo_delete(callback: CallbackQuery, session: AsyncSession) -> None:
    if not is_admin(callback.from_user.id):
        return await callback.answer("Нет доступа.", show_alert=True)
    promo_id = int(callback.data.split(":")[2])
    promo = await session.get(PromoCode, promo_id)
    if promo:
        await session.delete(promo)
        await session.commit()
    await callback.answer("Промокод удалён.")
    promos = (await session.execute(select(PromoCode).order_by(PromoCode.created_at.desc()))).scalars().all()
    await callback.message.edit_text("🎟 <b>Список промокодов:</b>", parse_mode="HTML", reply_markup=promo_list_kb(promos))


# ─── Credit ──────────────────────────────────────────────────────────────────

@router.callback_query(lambda c: c.data == "admin:credit")
async def cb_credit(callback: CallbackQuery, state: FSMContext) -> None:
    if not is_admin(callback.from_user.id):
        return await callback.answer("Нет доступа.", show_alert=True)
    await state.set_state(AdminCreditStates.user_id)
    await callback.message.edit_text("💳 Введи Telegram ID пользователя:")
    await callback.answer()


@router.message(AdminCreditStates.user_id)
async def msg_credit_user(message: Message, state: FSMContext, session: AsyncSession) -> None:
    try:
        uid = int(message.text.strip())
    except ValueError:
        await message.answer("❌ Введи числовой ID:")
        return
    user = await session.get(User, uid)
    if not user:
        await message.answer("❌ Пользователь не найден. Введи другой ID:")
        return
    await state.update_data(target_user_id=uid)
    await state.set_state(AdminCreditStates.amount)
    await message.answer(f"Пользователь: {user.first_name} (@{user.username})\nВведи сумму для начисления:")


@router.message(AdminCreditStates.amount)
async def msg_credit_amount(message: Message, state: FSMContext, session: AsyncSession) -> None:
    try:
        amount = float(message.text.strip().replace(",", "."))
    except ValueError:
        await message.answer("❌ Введи число:")
        return
    data = await state.get_data()
    await state.clear()

    user = await session.get(User, data["target_user_id"])
    user.stars_balance += amount
    await session.commit()

    await message.answer(
        f"✅ Начислено <b>{amount} ⭐</b> пользователю {user.first_name}.\n"
        f"Новый баланс: <b>{user.stars_balance:.2f} ⭐</b>",
        parse_mode="HTML",
        reply_markup=admin_main_kb(),
    )


# ─── Settings ────────────────────────────────────────────────────────────────

@router.callback_query(lambda c: c.data == "admin:settings")
async def cb_settings(callback: CallbackQuery, session: AsyncSession) -> None:
    if not is_admin(callback.from_user.id):
        return await callback.answer("Нет доступа.", show_alert=True)

    rr = (await session.get(BotSettings, "referral_reward"))
    bc = (await session.get(BotSettings, "bonus_cooldown_hours"))
    bmin = (await session.get(BotSettings, "bonus_min"))
    bmax = (await session.get(BotSettings, "bonus_max"))
    pch = (await session.get(BotSettings, "payments_channel_id"))
    pch_url = (await session.get(BotSettings, "payments_channel_url"))

    await callback.message.edit_text(
        f"⚙️ <b>Настройки</b>\n\n"
        f"⭐ Награда за реферала: <b>{rr.value if rr else '?'}</b>\n"
        f"⏱ Кулдаун бонуса: <b>{bc.value if bc else '?'} ч</b>\n"
        f"🎁 Бонус мин: <b>{bmin.value if bmin else '?'}</b>\n"
        f"🎁 Бонус макс: <b>{bmax.value if bmax else '?'}</b>\n"
        f"📢 ID канала выплат: <b>{pch.value if pch and pch.value else 'не задан'}</b>\n"
        f"🔗 Ссылка канала: <b>{pch_url.value if pch_url and pch_url.value else 'не задана'}</b>",
        parse_mode="HTML",
        reply_markup=admin_settings_kb(),
    )
    await callback.answer()


async def _ask_setting(callback: CallbackQuery, state: FSMContext, state_obj: State, prompt: str) -> None:
    await state.set_state(state_obj)
    await callback.message.edit_text(prompt)
    await callback.answer()


@router.callback_query(lambda c: c.data == "settings:referral_reward")
async def cb_set_rr(callback: CallbackQuery, state: FSMContext) -> None:
    if not is_admin(callback.from_user.id):
        return
    await _ask_setting(callback, state, AdminSettingsStates.referral_reward, "Введи новую награду за реферала (число):")


@router.callback_query(lambda c: c.data == "settings:bonus_cooldown")
async def cb_set_cooldown(callback: CallbackQuery, state: FSMContext) -> None:
    if not is_admin(callback.from_user.id):
        return
    await _ask_setting(callback, state, AdminSettingsStates.bonus_cooldown, "Введи кулдаун бонуса в часах (целое):")


@router.callback_query(lambda c: c.data == "settings:bonus_min")
async def cb_set_bmin(callback: CallbackQuery, state: FSMContext) -> None:
    if not is_admin(callback.from_user.id):
        return
    await _ask_setting(callback, state, AdminSettingsStates.bonus_min, "Введи минимальный бонус (число):")


@router.callback_query(lambda c: c.data == "settings:bonus_max")
async def cb_set_bmax(callback: CallbackQuery, state: FSMContext) -> None:
    if not is_admin(callback.from_user.id):
        return
    await _ask_setting(callback, state, AdminSettingsStates.bonus_max, "Введи максимальный бонус (число):")


@router.callback_query(lambda c: c.data == "settings:payments_channel_id")
async def cb_set_payments_channel(callback: CallbackQuery, state: FSMContext) -> None:
    if not is_admin(callback.from_user.id):
        return
    await state.set_state(AdminSettingsStates.payments_channel_id)
    await callback.message.edit_text(
        "📢 Введи ID канала выплат:\n"
        "Примеры: <code>-1001234567890</code> или <code>@mychannel</code>\n\n"
        "Бот должен быть администратором этого канала.",
        parse_mode="HTML",
    )
    await callback.answer()


async def _save_setting(message: Message, state: FSMContext, session: AsyncSession, key: str) -> None:
    try:
        val = float(message.text.strip().replace(",", "."))
    except ValueError:
        await message.answer("❌ Введи число:")
        return
    await state.clear()
    await set_setting(session, key, str(val))
    await message.answer(f"✅ Настройка обновлена: <b>{key}</b> = {val}", parse_mode="HTML", reply_markup=admin_main_kb())


@router.message(AdminSettingsStates.referral_reward)
async def msg_set_rr(message: Message, state: FSMContext, session: AsyncSession) -> None:
    await _save_setting(message, state, session, "referral_reward")


@router.message(AdminSettingsStates.bonus_cooldown)
async def msg_set_cooldown(message: Message, state: FSMContext, session: AsyncSession) -> None:
    await _save_setting(message, state, session, "bonus_cooldown_hours")


@router.message(AdminSettingsStates.bonus_min)
async def msg_set_bmin(message: Message, state: FSMContext, session: AsyncSession) -> None:
    await _save_setting(message, state, session, "bonus_min")


@router.message(AdminSettingsStates.bonus_max)
async def msg_set_bmax(message: Message, state: FSMContext, session: AsyncSession) -> None:
    await _save_setting(message, state, session, "bonus_max")


@router.message(AdminSettingsStates.payments_channel_id)
async def msg_set_payments_channel(message: Message, state: FSMContext, session: AsyncSession) -> None:
    await state.clear()
    value = message.text.strip()
    await set_setting(session, "payments_channel_id", value)
    await message.answer(
        f"✅ ID канала выплат установлен: <code>{value}</code>",
        parse_mode="HTML",
        reply_markup=admin_main_kb(),
    )


@router.callback_query(lambda c: c.data == "settings:payments_channel_url")
async def cb_set_payments_channel_url(callback: CallbackQuery, state: FSMContext) -> None:
    if not is_admin(callback.from_user.id):
        return
    await state.set_state(AdminSettingsStates.payments_channel_url)
    await callback.message.edit_text(
        "🔗 Введи публичную ссылку на канал выплат:\n"
        "Пример: <code>https://t.me/mychannel</code>",
        parse_mode="HTML",
    )
    await callback.answer()


@router.message(AdminSettingsStates.payments_channel_url)
async def msg_set_payments_channel_url(message: Message, state: FSMContext, session: AsyncSession) -> None:
    await state.clear()
    value = message.text.strip()
    await set_setting(session, "payments_channel_url", value)
    await message.answer(
        f"✅ Ссылка на канал выплат установлена: <code>{value}</code>",
        parse_mode="HTML",
        reply_markup=admin_main_kb(),
    )


# ─── Broadcast ───────────────────────────────────────────────────────────────

@router.callback_query(lambda c: c.data == "admin:broadcast")
async def cb_broadcast(callback: CallbackQuery, state: FSMContext) -> None:
    if not is_admin(callback.from_user.id):
        return await callback.answer("Нет доступа.", show_alert=True)
    await state.set_state(AdminBroadcastStates.text)
    await callback.message.edit_text("📢 Введи текст рассылки (HTML поддерживается):")
    await callback.answer()


@router.message(AdminBroadcastStates.text)
async def msg_broadcast(message: Message, state: FSMContext, session: AsyncSession, bot: Bot) -> None:
    await state.clear()
    text = message.text

    users = (await session.execute(select(User.user_id))).scalars().all()
    sent, failed = 0, 0
    for uid in users:
        try:
            await bot.send_message(uid, text, parse_mode="HTML")
            sent += 1
        except Exception:
            failed += 1

    await message.answer(
        f"✅ Рассылка завершена.\nДоставлено: <b>{sent}</b>\nОшибок: <b>{failed}</b>",
        parse_mode="HTML",
        reply_markup=admin_main_kb(),
    )


# ─── Withdrawal: Approve / Reject (from admin channel) ───────────────────────

@router.callback_query(lambda c: c.data and c.data.startswith("withdrawal:"))
async def cb_withdrawal_action(callback: CallbackQuery, session: AsyncSession, bot: Bot) -> None:
    if not is_admin(callback.from_user.id):
        return await callback.answer("Нет доступа.", show_alert=True)

    parts = callback.data.split(":")
    action, withdrawal_id = parts[1], int(parts[2])

    withdrawal = await session.get(Withdrawal, withdrawal_id)
    if not withdrawal:
        return await callback.answer("Заявка не найдена.", show_alert=True)
    if withdrawal.status != "pending":
        return await callback.answer(f"Заявка уже обработана: {withdrawal.status}", show_alert=True)

    withdrawal.status = "approved" if action == "approve" else "rejected"
    withdrawal.processed_at = datetime.utcnow()

    user = await session.get(User, withdrawal.user_id)
    if action == "reject" and user:
        user.stars_balance += withdrawal.amount

    await session.commit()

    status_text = "✅ Принята" if action == "approve" else "❌ Отклонена"

    # Update admin channel message (remove buttons, keep text)
    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass
    await callback.answer(status_text)

    # Edit payments channel message with updated status
    uname = user.username if user else "unknown"
    uid = withdrawal.user_id
    if withdrawal.payments_message_id:
        pch = await session.get(BotSettings, "payments_channel_id")
        if pch and pch.value:
            try:
                await bot.edit_message_text(
                    chat_id=pch.value,
                    message_id=withdrawal.payments_message_id,
                    text=build_withdrawal_msg(withdrawal.id, uname, uid, withdrawal.amount, withdrawal.status),
                    parse_mode="HTML",
                )
            except Exception:
                pass

    # Notify user
    try:
        if user:
            if action == "approve":
                notify = f"💸 Ваша заявка на вывод <b>{withdrawal.amount:.0f} ⭐</b> одобрена!"
            else:
                notify = f"❌ Ваша заявка на вывод <b>{withdrawal.amount:.0f} ⭐</b> отклонена."
            await bot.send_message(withdrawal.user_id, notify, parse_mode="HTML")
    except Exception:
        pass


# ─── Tasks: Management ───────────────────────────────────────────────────────

@router.callback_query(lambda c: c.data == "admin:tasks")
async def cb_admin_tasks(callback: CallbackQuery) -> None:
    if not is_admin(callback.from_user.id):
        return await callback.answer("Нет доступа.", show_alert=True)
    await callback.message.edit_text(
        "📋 <b>Управление заданиями</b>",
        parse_mode="HTML",
        reply_markup=task_management_kb(),
    )
    await callback.answer()


@router.callback_query(lambda c: c.data == "admin:list_tasks")
async def cb_list_tasks(callback: CallbackQuery, session: AsyncSession) -> None:
    if not is_admin(callback.from_user.id):
        return await callback.answer("Нет доступа.", show_alert=True)
    tasks = (await session.execute(select(Task).order_by(Task.created_at.desc()))).scalars().all()
    if not tasks:
        await callback.message.edit_text("Заданий нет.", reply_markup=task_management_kb())
        await callback.answer()
        return
    await callback.message.edit_text(
        "📋 <b>Список заданий:</b>",
        parse_mode="HTML",
        reply_markup=task_list_admin_kb(tasks),
    )
    await callback.answer()


@router.callback_query(lambda c: c.data and c.data.startswith("admin:task_info:"))
async def cb_task_info(callback: CallbackQuery, session: AsyncSession) -> None:
    if not is_admin(callback.from_user.id):
        return await callback.answer("Нет доступа.", show_alert=True)
    task_id = int(callback.data.split(":")[2])
    task = await session.get(Task, task_id)
    if not task:
        await callback.answer("Задание не найдено.", show_alert=True)
        return

    completions_count = (await session.execute(
        select(func.count(TaskCompletion.id)).where(TaskCompletion.task_id == task_id)
    )).scalar()

    type_label = {"subscribe": "📢 Подписка на канал", "referrals": "👥 Рефералы"}.get(task.task_type, task.task_type)
    status = "✅ Активно" if task.is_active else "❌ Неактивно"

    extra = ""
    if task.task_type == "subscribe":
        extra = f"\nКанал: <code>{task.channel_id}</code>"
    elif task.task_type == "referrals":
        extra = f"\nЦель: {task.target_value} рефералов"

    await callback.message.edit_text(
        f"📌 <b>{task.title}</b>\n\n"
        f"{task.description}\n\n"
        f"Тип: {type_label}\n"
        f"Награда: <b>{task.reward} ⭐</b>\n"
        f"Статус: {status}\n"
        f"Выполнений: <b>{completions_count}</b>"
        f"{extra}",
        parse_mode="HTML",
        reply_markup=task_actions_kb(task.id, task.is_active),
    )
    await callback.answer()


@router.callback_query(lambda c: c.data and c.data.startswith("admin:task_toggle:"))
async def cb_task_toggle(callback: CallbackQuery, session: AsyncSession) -> None:
    if not is_admin(callback.from_user.id):
        return await callback.answer("Нет доступа.", show_alert=True)
    task_id = int(callback.data.split(":")[2])
    task = await session.get(Task, task_id)
    if task:
        task.is_active = not task.is_active
        await session.commit()
        await callback.answer("Статус изменён.")
        await callback.message.edit_reply_markup(reply_markup=task_actions_kb(task.id, task.is_active))


@router.callback_query(lambda c: c.data and c.data.startswith("admin:task_delete:"))
async def cb_task_delete(callback: CallbackQuery, session: AsyncSession) -> None:
    if not is_admin(callback.from_user.id):
        return await callback.answer("Нет доступа.", show_alert=True)
    task_id = int(callback.data.split(":")[2])
    task = await session.get(Task, task_id)
    if task:
        await session.delete(task)
        await session.commit()
    await callback.answer("Задание удалено.")
    tasks = (await session.execute(select(Task).order_by(Task.created_at.desc()))).scalars().all()
    if not tasks:
        await callback.message.edit_text("Заданий нет.", reply_markup=task_management_kb())
    else:
        await callback.message.edit_text(
            "📋 <b>Список заданий:</b>",
            parse_mode="HTML",
            reply_markup=task_list_admin_kb(tasks),
        )


# ─── Tasks: Add (FSM) ────────────────────────────────────────────────────────

@router.callback_query(lambda c: c.data == "admin:add_task")
async def cb_add_task(callback: CallbackQuery, state: FSMContext) -> None:
    if not is_admin(callback.from_user.id):
        return await callback.answer("Нет доступа.", show_alert=True)
    await state.set_state(AdminTaskStates.task_type)
    await callback.message.edit_text("📋 Выбери тип задания:", reply_markup=task_type_kb())
    await callback.answer()


@router.callback_query(lambda c: c.data and c.data.startswith("task_type:"))
async def cb_task_type_chosen(callback: CallbackQuery, state: FSMContext) -> None:
    if not is_admin(callback.from_user.id):
        return await callback.answer("Нет доступа.", show_alert=True)
    task_type = callback.data.split(":")[1]
    await state.update_data(task_type=task_type)
    await state.set_state(AdminTaskStates.title)
    await callback.message.edit_text("✏️ Введи название задания:")
    await callback.answer()


@router.message(AdminTaskStates.title)
async def msg_task_title(message: Message, state: FSMContext) -> None:
    await state.update_data(title=message.text.strip())
    await state.set_state(AdminTaskStates.description)
    await message.answer("📝 Введи описание задания:")


@router.message(AdminTaskStates.description)
async def msg_task_description(message: Message, state: FSMContext) -> None:
    await state.update_data(description=message.text.strip())
    await state.set_state(AdminTaskStates.reward)
    await message.answer("💰 Введи награду (число, например: 5 или 2.5):")


@router.message(AdminTaskStates.reward)
async def msg_task_reward(message: Message, state: FSMContext, session: AsyncSession) -> None:
    try:
        reward = float(message.text.strip().replace(",", "."))
    except ValueError:
        await message.answer("❌ Введи число:")
        return
    data = await state.get_data()
    await state.update_data(reward=reward)

    if data["task_type"] == "subscribe":
        await state.set_state(AdminTaskStates.channel_id)
        await message.answer(
            "📢 Введи ID или username канала:\n"
            "Примеры: <code>@mychannel</code> или <code>-1001234567890</code>\n\n"
            "<b>Важно:</b> бот должен быть администратором канала для проверки подписки.",
            parse_mode="HTML",
        )
    elif data["task_type"] == "referrals":
        await state.set_state(AdminTaskStates.target_value)
        await message.answer("👥 Введи необходимое количество рефералов (целое число):")
    else:
        await _save_task(message, state, session)


@router.message(AdminTaskStates.channel_id)
async def msg_task_channel(message: Message, state: FSMContext, session: AsyncSession, bot: Bot) -> None:
    channel_id = message.text.strip()

    # Verify bot is an admin of the channel before saving the task
    try:
        bot_me = await bot.get_me()
        member = await bot.get_chat_member(channel_id, bot_me.id)
        if member.status not in ("administrator", "creator"):
            await message.answer(
                "❌ <b>Бот не является администратором канала.</b>\n\n"
                "Назначьте бота администратором с правом просмотра участников и повторите попытку.",
                parse_mode="HTML",
            )
            return
    except Exception as e:
        await message.answer(
            f"❌ <b>Не удалось получить доступ к каналу</b> <code>{channel_id}</code>\n\n"
            "Убедитесь, что:\n"
            "• Бот добавлен в канал\n"
            "• Бот назначен администратором\n"
            "• ID канала введён верно (например: <code>@mychannel</code> или <code>-1001234567890</code>)",
            parse_mode="HTML",
        )
        import logging
        logging.getLogger(__name__).warning("Channel access check failed for %s: %s", channel_id, e)
        return

    await state.update_data(channel_id=channel_id)
    await _save_task(message, state, session)


@router.message(AdminTaskStates.target_value)
async def msg_task_target(message: Message, state: FSMContext, session: AsyncSession) -> None:
    try:
        target = int(message.text.strip())
    except ValueError:
        await message.answer("❌ Введи целое число:")
        return
    await state.update_data(target_value=target)
    await _save_task(message, state, session)


async def _save_task(message: Message, state: FSMContext, session: AsyncSession) -> None:
    data = await state.get_data()
    await state.clear()

    task = Task(
        task_type=data["task_type"],
        title=data["title"],
        description=data["description"],
        reward=data["reward"],
        channel_id=data.get("channel_id"),
        target_value=data.get("target_value"),
    )
    session.add(task)
    await session.commit()

    type_label = {"subscribe": "📢 Подписка на канал", "referrals": "👥 Рефералы"}.get(data["task_type"], data["task_type"])
    extra = ""
    if data.get("channel_id"):
        extra = f"\nКанал: <code>{data['channel_id']}</code>"
    elif data.get("target_value"):
        extra = f"\nЦель: {data['target_value']} рефералов"

    await message.answer(
        f"✅ Задание создано!\n\n"
        f"<b>{data['title']}</b>\n"
        f"Тип: {type_label}\n"
        f"Награда: <b>{data['reward']} ⭐</b>"
        f"{extra}",
        parse_mode="HTML",
        reply_markup=admin_main_kb(),
    )


# ─── Games: Management ────────────────────────────────────────────────────────

_GAME_LABELS_ADMIN = {
    "football":   "⚽ Футбол",
    "basketball": "🏀 Баскетбол",
    "bowling":    "🎳 Боулинг",
    "dice":       "🎲 Кубики",
    "slots":      "🎰 Слоты",
}
_GAME_TYPES_ADMIN = ["football", "basketball", "bowling", "dice", "slots"]


async def _get_game_float(session: AsyncSession, key: str, default: float) -> float:
    row = await session.get(BotSettings, key)
    if row:
        try:
            return float(row.value)
        except ValueError:
            pass
    return default


@router.callback_query(lambda c: c.data == "admin:games")
async def cb_admin_games(callback: CallbackQuery, session: AsyncSession) -> None:
    if not is_admin(callback.from_user.id):
        return await callback.answer("Нет доступа.", show_alert=True)

    statuses = {}
    for game in _GAME_TYPES_ADMIN:
        row = await session.get(BotSettings, f"game_{game}_enabled")
        statuses[game] = (row.value == "1") if row else True

    await callback.message.edit_text(
        "🎮 <b>Управление играми</b>\n\nВыбери игру для настройки:",
        parse_mode="HTML",
        reply_markup=games_list_kb(statuses),
    )
    await callback.answer()


@router.callback_query(lambda c: c.data and c.data.startswith("agame:info:"))
async def cb_admin_game_info(callback: CallbackQuery, session: AsyncSession) -> None:
    if not is_admin(callback.from_user.id):
        return await callback.answer("Нет доступа.", show_alert=True)

    game_type = callback.data.split(":")[2]
    label = _GAME_LABELS_ADMIN.get(game_type, game_type)

    enabled_row = await session.get(BotSettings, f"game_{game_type}_enabled")
    is_enabled = (enabled_row.value == "1") if enabled_row else True
    min_bet = await _get_game_float(session, f"game_{game_type}_min_bet", 1.0)
    daily_limit_row = await session.get(BotSettings, f"game_{game_type}_daily_limit")
    daily_limit = int(daily_limit_row.value) if daily_limit_row else 0

    if game_type == "slots":
        c1 = await _get_game_float(session, "game_slots_coeff1", 5.0)
        c2 = await _get_game_float(session, "game_slots_coeff2", 2.0)
        coeff_line = f"📈 Коэф. Tier 1 (1–3): <b>x{c1}</b>\n📈 Коэф. Tier 2 (4–10): <b>x{c2}</b>"
    else:
        coeff = await _get_game_float(session, f"game_{game_type}_coeff", 1.0)
        coeff_line = f"📈 Коэффициент: <b>x{coeff}</b>"

    status_text = "✅ Включена" if is_enabled else "❌ Отключена"
    limit_text = str(daily_limit) if daily_limit > 0 else "∞ (без лимита)"

    await callback.message.edit_text(
        f"🎮 <b>{label}</b>\n\n"
        f"Статус: {status_text}\n"
        f"{coeff_line}\n"
        f"💰 Мин. ставка: <b>{min_bet:.0f} ⭐</b>\n"
        f"🔢 Лимит в день: <b>{limit_text}</b>",
        parse_mode="HTML",
        reply_markup=game_detail_kb(game_type, is_enabled),
    )
    await callback.answer()


@router.callback_query(lambda c: c.data and c.data.startswith("agame:toggle:"))
async def cb_admin_game_toggle(callback: CallbackQuery, session: AsyncSession) -> None:
    if not is_admin(callback.from_user.id):
        return await callback.answer("Нет доступа.", show_alert=True)

    game_type = callback.data.split(":")[2]
    key = f"game_{game_type}_enabled"
    row = await session.get(BotSettings, key)
    new_val = "0" if (row and row.value == "1") else "1"
    await set_setting(session, key, new_val)

    await callback.answer("Статус изменён.")
    # Refresh info page
    callback.data = f"agame:info:{game_type}"
    await cb_admin_game_info(callback, session)


@router.callback_query(lambda c: c.data and c.data.startswith("agame:coeff:"))
async def cb_admin_game_coeff(callback: CallbackQuery, state: FSMContext) -> None:
    if not is_admin(callback.from_user.id):
        return await callback.answer("Нет доступа.", show_alert=True)
    game_type = callback.data.split(":")[2]
    await state.set_state(AdminGameStates.set_coeff)
    await state.update_data(game_type=game_type)
    await callback.message.edit_text(
        f"📈 Введи новый коэффициент для {_GAME_LABELS_ADMIN[game_type]} (например: 3.0):"
    )
    await callback.answer()


@router.callback_query(lambda c: c.data and c.data.startswith("agame:coeff1:"))
async def cb_admin_game_coeff1(callback: CallbackQuery, state: FSMContext) -> None:
    if not is_admin(callback.from_user.id):
        return await callback.answer("Нет доступа.", show_alert=True)
    await state.set_state(AdminGameStates.set_coeff1)
    await state.update_data(game_type="slots")
    await callback.message.edit_text("📈 Введи коэффициент Tier 1 🎰 (значения 1–3), например: 5.0:")
    await callback.answer()


@router.callback_query(lambda c: c.data and c.data.startswith("agame:coeff2:"))
async def cb_admin_game_coeff2(callback: CallbackQuery, state: FSMContext) -> None:
    if not is_admin(callback.from_user.id):
        return await callback.answer("Нет доступа.", show_alert=True)
    await state.set_state(AdminGameStates.set_coeff2)
    await state.update_data(game_type="slots")
    await callback.message.edit_text("📈 Введи коэффициент Tier 2 🎰 (значения 4–10), например: 2.0:")
    await callback.answer()


@router.callback_query(lambda c: c.data and c.data.startswith("agame:min_bet:"))
async def cb_admin_game_min_bet(callback: CallbackQuery, state: FSMContext) -> None:
    if not is_admin(callback.from_user.id):
        return await callback.answer("Нет доступа.", show_alert=True)
    game_type = callback.data.split(":")[2]
    await state.set_state(AdminGameStates.set_min_bet)
    await state.update_data(game_type=game_type)
    await callback.message.edit_text(f"💰 Введи минимальную ставку для {_GAME_LABELS_ADMIN[game_type]} (например: 1):")
    await callback.answer()


@router.callback_query(lambda c: c.data and c.data.startswith("agame:daily_limit:"))
async def cb_admin_game_daily_limit(callback: CallbackQuery, state: FSMContext) -> None:
    if not is_admin(callback.from_user.id):
        return await callback.answer("Нет доступа.", show_alert=True)
    game_type = callback.data.split(":")[2]
    await state.set_state(AdminGameStates.set_daily_limit)
    await state.update_data(game_type=game_type)
    await callback.message.edit_text(
        f"🔢 Введи лимит игр в день для {_GAME_LABELS_ADMIN[game_type]}:\n(0 = без ограничений)"
    )
    await callback.answer()


@router.message(AdminGameStates.set_coeff)
async def msg_admin_game_coeff(message: Message, state: FSMContext, session: AsyncSession) -> None:
    try:
        val = float(message.text.strip().replace(",", "."))
        if val <= 0:
            raise ValueError
    except ValueError:
        await message.answer("❌ Введи положительное число:")
        return
    data = await state.get_data()
    await state.clear()
    game_type = data["game_type"]
    await set_setting(session, f"game_{game_type}_coeff", str(val))
    await message.answer(
        f"✅ Коэффициент {_GAME_LABELS_ADMIN[game_type]} установлен: <b>x{val}</b>",
        parse_mode="HTML",
        reply_markup=admin_main_kb(),
    )


@router.message(AdminGameStates.set_coeff1)
async def msg_admin_game_coeff1(message: Message, state: FSMContext, session: AsyncSession) -> None:
    try:
        val = float(message.text.strip().replace(",", "."))
        if val <= 0:
            raise ValueError
    except ValueError:
        await message.answer("❌ Введи положительное число:")
        return
    await state.clear()
    await set_setting(session, "game_slots_coeff1", str(val))
    await message.answer(
        f"✅ Коэффициент Tier 1 🎰 установлен: <b>x{val}</b>",
        parse_mode="HTML",
        reply_markup=admin_main_kb(),
    )


@router.message(AdminGameStates.set_coeff2)
async def msg_admin_game_coeff2(message: Message, state: FSMContext, session: AsyncSession) -> None:
    try:
        val = float(message.text.strip().replace(",", "."))
        if val <= 0:
            raise ValueError
    except ValueError:
        await message.answer("❌ Введи положительное число:")
        return
    await state.clear()
    await set_setting(session, "game_slots_coeff2", str(val))
    await message.answer(
        f"✅ Коэффициент Tier 2 🎰 установлен: <b>x{val}</b>",
        parse_mode="HTML",
        reply_markup=admin_main_kb(),
    )


@router.message(AdminGameStates.set_min_bet)
async def msg_admin_game_min_bet(message: Message, state: FSMContext, session: AsyncSession) -> None:
    try:
        val = float(message.text.strip().replace(",", "."))
        if val <= 0:
            raise ValueError
    except ValueError:
        await message.answer("❌ Введи положительное число:")
        return
    data = await state.get_data()
    await state.clear()
    game_type = data["game_type"]
    await set_setting(session, f"game_{game_type}_min_bet", str(val))
    await message.answer(
        f"✅ Мин. ставка {_GAME_LABELS_ADMIN[game_type]}: <b>{val:.0f} ⭐</b>",
        parse_mode="HTML",
        reply_markup=admin_main_kb(),
    )


@router.message(AdminGameStates.set_daily_limit)
async def msg_admin_game_daily_limit(message: Message, state: FSMContext, session: AsyncSession) -> None:
    try:
        val = int(message.text.strip())
        if val < 0:
            raise ValueError
    except ValueError:
        await message.answer("❌ Введи целое неотрицательное число (0 = без лимита):")
        return
    data = await state.get_data()
    await state.clear()
    game_type = data["game_type"]
    await set_setting(session, f"game_{game_type}_daily_limit", str(val))
    limit_text = str(val) if val > 0 else "∞ (без лимита)"
    await message.answer(
        f"✅ Лимит в день {_GAME_LABELS_ADMIN[game_type]}: <b>{limit_text}</b>",
        parse_mode="HTML",
        reply_markup=admin_main_kb(),
    )


# ─── Button Content Management ────────────────────────────────────────────────

async def _show_button_content_list(target, session: AsyncSession) -> None:
    contents = {}
    for key in BUTTON_KEYS:
        row = await get_button_content(session, key)
        contents[key] = bool(row and (row.photo_file_id or row.text))

    text = (
        "🖼 <b>Фото и текст кнопок</b>\n\n"
        "🖼 — настроено  |  ⬜ — пусто\n\n"
        "Нажми на кнопку, чтобы настроить фото и текст для неё:"
    )
    if isinstance(target, CallbackQuery):
        await target.message.edit_text(text, parse_mode="HTML", reply_markup=button_content_list_kb(contents))
        await target.answer()
    else:
        await target.answer(text, parse_mode="HTML", reply_markup=button_content_list_kb(contents))


@router.callback_query(lambda c: c.data == "admin:button_content")
async def cb_button_content(callback: CallbackQuery, session: AsyncSession) -> None:
    if not is_admin(callback.from_user.id):
        return await callback.answer("Нет доступа.", show_alert=True)
    await _show_button_content_list(callback, session)


async def _show_button_edit(target, session: AsyncSession, button_key: str) -> None:
    label = BUTTON_KEYS.get(button_key, button_key)
    row = await get_button_content(session, button_key)
    has_photo = bool(row and row.photo_file_id)
    has_text = bool(row and row.text)

    photo_status = "✅ Установлено" if has_photo else "❌ Не установлено"
    text_status = f"✅ Установлен ({len(row.text)} симв.)" if has_text else "❌ Не установлен"

    info = (
        f"🖼 <b>{label}</b>\n\n"
        f"Фото: {photo_status}\n"
        f"Текст: {text_status}"
    )

    send = target.message.edit_text if isinstance(target, CallbackQuery) else target.answer
    kb = button_edit_kb(button_key, has_photo, has_text)
    await send(info, parse_mode="HTML", reply_markup=kb)
    if isinstance(target, CallbackQuery):
        await target.answer()


@router.callback_query(lambda c: c.data and c.data.startswith("admin:btn_edit:"))
async def cb_btn_edit(callback: CallbackQuery, session: AsyncSession) -> None:
    if not is_admin(callback.from_user.id):
        return await callback.answer("Нет доступа.", show_alert=True)
    button_key = callback.data[len("admin:btn_edit:"):]
    if button_key not in BUTTON_KEYS:
        return await callback.answer("Кнопка не найдена.", show_alert=True)
    await _show_button_edit(callback, session, button_key)


@router.callback_query(lambda c: c.data and c.data.startswith("admin:btn_set_photo:"))
async def cb_btn_set_photo(callback: CallbackQuery, state: FSMContext) -> None:
    if not is_admin(callback.from_user.id):
        return await callback.answer("Нет доступа.", show_alert=True)
    button_key = callback.data[len("admin:btn_set_photo:"):]
    await state.set_state(AdminButtonContentStates.set_photo)
    await state.update_data(button_key=button_key)
    await callback.message.edit_text(
        f"🖼 Отправь фото для кнопки <b>{BUTTON_KEYS.get(button_key, button_key)}</b>:\n\n"
        "Просто пришли изображение в этот чат.",
        parse_mode="HTML",
    )
    await callback.answer()


@router.message(AdminButtonContentStates.set_photo)
async def msg_btn_set_photo(message: Message, state: FSMContext, session: AsyncSession) -> None:
    if not message.photo:
        await message.answer("❌ Пришли именно фото (изображение), а не файл или текст.")
        return
    data = await state.get_data()
    await state.clear()
    button_key = data["button_key"]
    file_id = message.photo[-1].file_id
    await set_button_photo(session, button_key, file_id)
    await message.answer(
        f"✅ Фото для кнопки <b>{BUTTON_KEYS.get(button_key, button_key)}</b> установлено!",
        parse_mode="HTML",
        reply_markup=button_edit_kb(
            button_key,
            has_photo=True,
            has_text=bool((await get_button_content(session, button_key)) and
                          (await get_button_content(session, button_key)).text),
        ),
    )


@router.callback_query(lambda c: c.data and c.data.startswith("admin:btn_set_text:"))
async def cb_btn_set_text(callback: CallbackQuery, state: FSMContext) -> None:
    if not is_admin(callback.from_user.id):
        return await callback.answer("Нет доступа.", show_alert=True)
    button_key = callback.data[len("admin:btn_set_text:"):]
    await state.set_state(AdminButtonContentStates.set_text)
    await state.update_data(button_key=button_key)
    await callback.message.edit_text(
        f"📝 Введи текст для кнопки <b>{BUTTON_KEYS.get(button_key, button_key)}</b>:\n\n"
        "Поддерживается HTML-разметка: <b>жирный</b>, <i>курсив</i>, <code>моноширинный</code>.",
        parse_mode="HTML",
    )
    await callback.answer()


@router.message(AdminButtonContentStates.set_text)
async def msg_btn_set_text(message: Message, state: FSMContext, session: AsyncSession) -> None:
    data = await state.get_data()
    await state.clear()
    button_key = data["button_key"]
    await set_button_text(session, button_key, message.text or message.caption or "")
    row = await get_button_content(session, button_key)
    await message.answer(
        f"✅ Текст для кнопки <b>{BUTTON_KEYS.get(button_key, button_key)}</b> установлен!",
        parse_mode="HTML",
        reply_markup=button_edit_kb(
            button_key,
            has_photo=bool(row and row.photo_file_id),
            has_text=True,
        ),
    )


@router.callback_query(lambda c: c.data and c.data.startswith("admin:btn_del_photo:"))
async def cb_btn_del_photo(callback: CallbackQuery, session: AsyncSession) -> None:
    if not is_admin(callback.from_user.id):
        return await callback.answer("Нет доступа.", show_alert=True)
    button_key = callback.data[len("admin:btn_del_photo:"):]
    await set_button_photo(session, button_key, None)
    await callback.answer("Фото удалено.")
    await _show_button_edit(callback, session, button_key)


@router.callback_query(lambda c: c.data and c.data.startswith("admin:btn_del_text:"))
async def cb_btn_del_text(callback: CallbackQuery, session: AsyncSession) -> None:
    if not is_admin(callback.from_user.id):
        return await callback.answer("Нет доступа.", show_alert=True)
    button_key = callback.data[len("admin:btn_del_text:"):]
    await set_button_text(session, button_key, None)
    await callback.answer("Текст удалён.")
    await _show_button_edit(callback, session, button_key)
