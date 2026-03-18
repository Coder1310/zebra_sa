from __future__ import annotations

import asyncio

from aiogram import Bot, Dispatcher

from zebra_bot.config import LOGS_DIR, PROJECT_ROOT, env, load_dotenv
from zebra_bot.handlers import router


async def main() -> None:
  load_dotenv(PROJECT_ROOT / ".env")
  LOGS_DIR.mkdir(parents = True, exist_ok = True)

  bot = Bot(token = env("BOT_TOKEN"))
  dp = Dispatcher()
  dp.include_router(router)

  try:
    await dp.start_polling(bot)
  finally:
    await bot.session.close()


def run() -> None:
  asyncio.run(main())