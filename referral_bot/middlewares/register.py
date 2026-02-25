from typing import Callable, Awaitable, Any

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject, Message, CallbackQuery

from database.engine import SessionFactory
from config import config


class SessionMiddleware(BaseMiddleware):
    """Injects async DB session into every handler."""

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        async with SessionFactory() as session:
            data["session"] = session
            return await handler(event, data)


class FlyerMiddleware(BaseMiddleware):
    """
    Enforces Flyer channel-subscription check before any bot feature.

    /admin is whitelisted — admins always bypass.
    When FLYER_KEY is not set in .env the check is skipped entirely.
    If the user is not subscribed, Flyer sends the subscription wall
    automatically — no extra message is needed from our side.
    """

    # Commands that never go through the Flyer check
    _SKIP_COMMANDS = {"/admin"}

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        from services.flyer import check_subscription

        if isinstance(event, Message):
            user = event.from_user
            text = event.text or ""
            if any(text.startswith(cmd) for cmd in self._SKIP_COMMANDS):
                return await handler(event, data)

        elif isinstance(event, CallbackQuery):
            user = event.from_user

        else:
            return await handler(event, data)

        if user is None:
            return await handler(event, data)

        # Admins always bypass
        if user.id in config.ADMIN_IDS:
            return await handler(event, data)

        subscribed = await check_subscription(
            user_id=user.id,
            language_code=user.language_code,
        )

        if not subscribed:
            # Flyer already sent the subscription wall to the user.
            # For callback queries we must answer to remove the loading spinner.
            if isinstance(event, CallbackQuery):
                try:
                    await event.answer()
                except Exception:
                    pass
            return  # block further handler execution

        return await handler(event, data)


class RegisteredUserMiddleware(BaseMiddleware):
    """
    Blocks unregistered users from using the bot without /start.
    Admins always bypass this check.
    """

    SKIP_TEXT = {"/start", "/admin"}

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        from database.models import User

        user = None
        if isinstance(event, Message):
            user = event.from_user
        elif isinstance(event, CallbackQuery):
            user = event.from_user
        else:
            return await handler(event, data)

        if user is None:
            return

        # Admins: try to load db_user; if not registered yet — require /start first
        if user.id in config.ADMIN_IDS:
            session = data.get("session")
            db_user = None
            if session:
                db_user = await session.get(User, user.id)
            if db_user:
                data["db_user"] = db_user
                return await handler(event, data)
            # Admin not in DB yet — allow /start and /admin, block the rest
            if isinstance(event, Message):
                text = event.text or ""
                if any(text.startswith(cmd) for cmd in {"/start", "/admin"}):
                    return await handler(event, data)
                await event.answer("Нажми /start чтобы начать.")
            elif isinstance(event, CallbackQuery):
                await event.answer("Сначала нажми /start.", show_alert=True)
            return

        # Skip /start and /admin for regular users too
        if isinstance(event, Message):
            text = event.text or ""
            if any(text.startswith(cmd) for cmd in self.SKIP_TEXT):
                return await handler(event, data)

        session = data.get("session")
        if session is None:
            return

        db_user = await session.get(User, user.id)
        if db_user is None:
            if isinstance(event, Message):
                await event.answer("Нажми /start чтобы начать.")
            elif isinstance(event, CallbackQuery):
                await event.answer("Сначала нажми /start.", show_alert=True)
            return

        data["db_user"] = db_user
        return await handler(event, data)
