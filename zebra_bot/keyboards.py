from __future__ import annotations

from aiogram.types import KeyboardButton, ReplyKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder


MAX_INLINE_TARGETS = 10
PER_PAGE = 10


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
  keyboard = InlineKeyboardBuilder()
  keyboard.button(text="✅ Join", callback_data=f"l:{lobby_chat_id}:{lobby_id}:join")
  keyboard.button(text="❌ Leave", callback_data=f"l:{lobby_chat_id}:{lobby_id}:leave")
  keyboard.button(text="🚀 Start now (host)", callback_data=f"l:{lobby_chat_id}:{lobby_id}:start")
  keyboard.button(text="🛑 Cancel (host)", callback_data=f"l:{lobby_chat_id}:{lobby_id}:cancel")
  keyboard.adjust(2, 2)
  return keyboard.as_markup()


def kb_finish_vote(lobby_chat_id: int):
  keyboard = InlineKeyboardBuilder()
  keyboard.button(text="✅ Завершить", callback_data=f"v:{lobby_chat_id}:yes")
  keyboard.button(text="❌ Продолжать", callback_data=f"v:{lobby_chat_id}:no")
  keyboard.adjust(2)
  return keyboard.as_markup()


def kb_pet_offer_answer(lobby_chat_id: int, uid: int, offerer_role: str):
  keyboard = InlineKeyboardBuilder()
  keyboard.button(text="✅ Принять", callback_data=f"a:{lobby_chat_id}:{uid}:pet_accept:{offerer_role}")
  keyboard.button(text="❌ Отказаться", callback_data=f"a:{lobby_chat_id}:{uid}:pet_decline:{offerer_role}")
  keyboard.adjust(2)
  return keyboard.as_markup()


def kb_house_offer_answer(lobby_chat_id: int, uid: int, offerer_role: str):
  keyboard = InlineKeyboardBuilder()
  keyboard.button(text="✅ Принять", callback_data=f"a:{lobby_chat_id}:{uid}:house_accept:{offerer_role}")
  keyboard.button(text="❌ Отказаться", callback_data=f"a:{lobby_chat_id}:{uid}:house_decline:{offerer_role}")
  keyboard.adjust(2)
  return keyboard.as_markup()


def kb_pet_targets(lobby_chat_id: int, uid: int, targets: list[str]):
  keyboard = InlineKeyboardBuilder()
  for target in targets[:MAX_INLINE_TARGETS]:
    keyboard.button(text=f"Swap with {target}", callback_data=f"a:{lobby_chat_id}:{uid}:pet_offer:{target}")
  keyboard.button(text="Cancel", callback_data=f"a:{lobby_chat_id}:{uid}:noop")
  keyboard.adjust(2, 2, 2, 2)
  return keyboard.as_markup()


def kb_house_targets(lobby_chat_id: int, uid: int, targets: list[str]):
  keyboard = InlineKeyboardBuilder()
  for target in targets[:MAX_INLINE_TARGETS]:
    keyboard.button(text=f"Swap home with {target}", callback_data=f"a:{lobby_chat_id}:{uid}:house_offer:{target}")
  keyboard.button(text="Cancel", callback_data=f"a:{lobby_chat_id}:{uid}:noop")
  keyboard.adjust(2, 2, 2, 2)
  return keyboard.as_markup()


def kb_goto_page(lobby_chat_id: int, uid: int, houses: int, page: int, current: int):
  start = page * PER_PAGE + 1
  end = min(houses, start + PER_PAGE - 1)

  keyboard = InlineKeyboardBuilder()
  for house in range(start, end + 1):
    if house == current:
      continue
    keyboard.button(text=f"Go {house}", callback_data=f"a:{lobby_chat_id}:{uid}:go_to:{house}")

  if page > 0:
    keyboard.button(text="⬅ Prev", callback_data=f"g:{lobby_chat_id}:{uid}:{page - 1}")
  if end < houses:
    keyboard.button(text="Next ➡", callback_data=f"g:{lobby_chat_id}:{uid}:{page + 1}")

  keyboard.button(text="Close", callback_data=f"a:{lobby_chat_id}:{uid}:noop")
  keyboard.adjust(5, 2, 1)
  return keyboard.as_markup()


def kb_actions_for_player(lobby_chat_id: int, uid: int, player_state: dict):
  keyboard = InlineKeyboardBuilder()

  trip = player_state.get("trip") or {}
  in_trip = bool(trip.get("active"))
  left = int(player_state.get("left_house", 1))
  right = int(player_state.get("right_house", 1))
  offers_in = list(player_state.get("pet_offers_in") or [])
  house_offers_in = list(player_state.get("house_offers_in") or [])
  co_located = list(player_state.get("co_located_all") or [])

  if in_trip:
    keyboard.button(text="⏳ Вы в пути - просто ждать", callback_data=f"a:{lobby_chat_id}:{uid}:noop")
  else:
    keyboard.button(text="⏸ Stay", callback_data=f"a:{lobby_chat_id}:{uid}:stay")
    keyboard.button(text=f"⬅ Left (to {left})", callback_data=f"a:{lobby_chat_id}:{uid}:left")
    keyboard.button(text=f"➡ Right (to {right})", callback_data=f"a:{lobby_chat_id}:{uid}:right")

    if co_located:
      keyboard.button(text="🐾 Предложить обмен питомцами", callback_data=f"p:{lobby_chat_id}:{uid}")
      keyboard.button(text="🏠 Предложить обмен домами", callback_data=f"h:{lobby_chat_id}:{uid}")

  for offerer in offers_in[:4]:
    keyboard.button(text=f"✅ Принять обмен от {offerer}", callback_data=f"a:{lobby_chat_id}:{uid}:pet_accept:{offerer}")
    keyboard.button(text=f"❌ Отказаться от {offerer}", callback_data=f"a:{lobby_chat_id}:{uid}:pet_decline:{offerer}")
  for offerer in house_offers_in[:4]:
    keyboard.button(text=f"✅ Принять дом от {offerer}", callback_data=f"a:{lobby_chat_id}:{uid}:house_accept:{offerer}")
    keyboard.button(text=f"❌ Отказаться от дома {offerer}", callback_data=f"a:{lobby_chat_id}:{uid}:house_decline:{offerer}")

  keyboard.button(text="🛑 End game", callback_data=f"e:{lobby_chat_id}:{uid}")
  keyboard.adjust(2, 2, 2)
  return keyboard.as_markup()
