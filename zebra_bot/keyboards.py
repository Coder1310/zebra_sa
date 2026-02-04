from __future__ import annotations

from aiogram.types import (
  ReplyKeyboardMarkup,
  KeyboardButton,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder


def kb_main_menu() -> ReplyKeyboardMarkup:
  return ReplyKeyboardMarkup(
    keyboard=[
      [KeyboardButton(text="🎮 Создать игру"), KeyboardButton(text="❓ Помощь")],
      [KeyboardButton(text="🧹 Скрыть меню")],
    ],
    resize_keyboard=True,
    one_time_keyboard=False,
    selective=True,
  )


def kb_lobby(lobby_chat_id: int, lobby_id: str):
  kb = InlineKeyboardBuilder()
  kb.button(text="✅ Join", callback_data=f"l:{lobby_chat_id}:{lobby_id}:join")
  kb.button(text="❌ Leave", callback_data=f"l:{lobby_chat_id}:{lobby_id}:leave")
  kb.button(text="🚀 Start now (host)", callback_data=f"l:{lobby_chat_id}:{lobby_id}:start")
  kb.button(text="🛑 Cancel (host)", callback_data=f"l:{lobby_chat_id}:{lobby_id}:cancel")
  kb.adjust(2, 2)
  return kb.as_markup()


def kb_finish_vote(lobby_chat_id: int):
  kb = InlineKeyboardBuilder()
  kb.button(text="✅ Завершить", callback_data=f"v:{lobby_chat_id}:yes")
  kb.button(text="❌ Продолжать", callback_data=f"v:{lobby_chat_id}:no")
  kb.adjust(2)
  return kb.as_markup()


def kb_pet_offer_answer(lobby_chat_id: int, uid: int, offerer_role: str):
  kb = InlineKeyboardBuilder()
  kb.button(text="✅ Принять", callback_data=f"a:{lobby_chat_id}:{uid}:pet_accept:{offerer_role}")
  kb.button(text="❌ Отказаться", callback_data=f"a:{lobby_chat_id}:{uid}:pet_decline:{offerer_role}")
  kb.adjust(2)
  return kb.as_markup()


def kb_pet_targets(lobby_chat_id: int, uid: int, targets: list[str]):
  kb = InlineKeyboardBuilder()
  for t in targets[:10]:
    kb.button(text=f"Swap with {t}", callback_data=f"a:{lobby_chat_id}:{uid}:pet_offer:{t}")
  kb.button(text="Cancel", callback_data=f"a:{lobby_chat_id}:{uid}:noop")
  kb.adjust(2, 2, 2, 2)
  return kb.as_markup()


def kb_goto_page(lobby_chat_id: int, uid: int, houses: int, page: int, current: int):
  per_page = 10
  start = page * per_page + 1
  end = min(houses, start + per_page - 1)

  kb = InlineKeyboardBuilder()
  for h in range(start, end + 1):
    if h == current:
      continue
    kb.button(text=f"Go {h}", callback_data=f"a:{lobby_chat_id}:{uid}:go_to:{h}")

  if page > 0:
    kb.button(text="⬅ Prev", callback_data=f"g:{lobby_chat_id}:{uid}:{page-1}")
  if end < houses:
    kb.button(text="Next ➡", callback_data=f"g:{lobby_chat_id}:{uid}:{page+1}")

  kb.button(text="Close", callback_data=f"a:{lobby_chat_id}:{uid}:noop")
  kb.adjust(5, 2, 1)
  return kb.as_markup()


def kb_actions_for_player(lobby_chat_id: int, uid: int, ps: dict):
  kb = InlineKeyboardBuilder()

  trip = ps.get("trip") or {}
  in_trip = bool(trip.get("active"))

  graph = str(ps.get("graph", "ring"))
  left = int(ps.get("left_house", 1))
  right = int(ps.get("right_house", 1))
  offers_in = ps.get("pet_offers_in") or []
  co_humans = ps.get("co_located_humans") or []

  if in_trip:
    kb.button(text="⏳ Вы в пути - просто ждать", callback_data=f"a:{lobby_chat_id}:{uid}:noop")
  else:
    kb.button(text="⏸ Stay", callback_data=f"a:{lobby_chat_id}:{uid}:stay")
    if graph != "full":
      kb.button(text=f"⬅ Left (to {left})", callback_data=f"a:{lobby_chat_id}:{uid}:left")
      kb.button(text=f"➡ Right (to {right})", callback_data=f"a:{lobby_chat_id}:{uid}:right")
    else:
      kb.button(text="🏃 Choose destination", callback_data=f"g:{lobby_chat_id}:{uid}:0")

    if len(co_humans) > 0:
      kb.button(text="🐾 Предложить обмен питомцами", callback_data=f"p:{lobby_chat_id}:{uid}")

  for offerer in offers_in[:4]:
    kb.button(text=f"✅ Принять обмен от {offerer}", callback_data=f"a:{lobby_chat_id}:{uid}:pet_accept:{offerer}")
    kb.button(text=f"❌ Отказаться от {offerer}", callback_data=f"a:{lobby_chat_id}:{uid}:pet_decline:{offerer}")

  kb.button(text="🛑 End game", callback_data=f"e:{lobby_chat_id}:{uid}")
  kb.adjust(2, 2, 2)
  return kb.as_markup()
