from __future__ import annotations

import asyncio
from pathlib import Path

from aiogram import Bot, Dispatcher
from dotenv import load_dotenv

from zebra_bot.config import BOT_TOKEN, PROJECT_ROOT
from zebra_bot.handlers import router


def _load_env() -> None:
  env_path = Path(PROJECT_ROOT) / ".env"
  if env_path.exists():
    load_dotenv(env_path)


async def _run() -> None:
  _load_env()

  token = BOT_TOKEN()
  if not token:
    raise RuntimeError("BOT_TOKEN is not set")

  bot = Bot(token=token)
  dp = Dispatcher()
  dp.include_router(router)

  try:
    await dp.start_polling(bot)
  finally:
    await bot.session.close()


def main() -> None:
  asyncio.run(_run())


if __name__ == "__main__":
  main()