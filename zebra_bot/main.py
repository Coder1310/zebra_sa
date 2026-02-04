from __future__ import annotations

import asyncio

from aiogram import Bot, Dispatcher

from zebra_bot.config import PROJECT_ROOT, load_dotenv, env
from zebra_bot.handlers import router


async def main() -> None:
  load_dotenv(PROJECT_ROOT / ".env")
  token = env("BOT_TOKEN")

  bot = Bot(token=token)
  dp = Dispatcher()
  dp.include_router(router)
  await dp.start_polling(bot)


def run() -> None:
  asyncio.run(main())
