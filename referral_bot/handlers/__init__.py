from handlers import start, earn, bonus, profile, promo, withdraw, tasks, top, games, admin

routers = [
    start.router,
    earn.router,
    bonus.router,
    profile.router,
    promo.router,
    withdraw.router,
    tasks.router,
    top.router,
    games.router,
    admin.router,
]

__all__ = ["routers"]
