from __future__ import annotations

from typing import Any

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message, ReplyKeyboardRemove

from zebra_bot import api
from zebra_bot.game_flow import (
  create_lobby,
  finish_game_now,
  maybe_step_and_next,
  notify_house_answer,
  notify_house_offer,
  notify_pet_answer,
  notify_pet_offer,
  request_finish,
  send_private_turn_state,
  start_game,
  sync_lobby_message,
)
from zebra_bot.keyboards import kb_finish_vote, kb_house_targets, kb_main_menu, kb_pet_targets
from zebra_bot.storage import draft_get, draft_set, get_game, load_state, remember_user, save_state, set_game


router = Router()

HELP_TEXT = (
  "🎮 Создать игру - создаст лобби в этом чате.\n"
  "Дальше игроки жмут Join.\n\n"
  "Команды:\n"
  "/game @user1 @user2 ...\n"
  "/end"
)

START_TEXT = (
  "🎮 ZEBRA\n"
  "Схема: группа - сцена, личка - приватные ходы.\n"
  "Чтобы приглашения и приватные ходы работали, нужно один раз нажать /start в личке."
)


class CallbackDataError(ValueError):
  pass


def _touch_user(user: Any) -> dict[str, Any]:
  state = load_state()
  remember_user(state, user)
  save_state(state)
  return state


def _unique_usernames(text: str) -> list[str]:
  names: list[str] = []
  for token in text.split():
    if token.startswith("@") and len(token) > 1:
      names.append(token[1:].lower())
  return list(dict.fromkeys(names))


def _parse_exact(data: str, expected_parts: int) -> list[str]:
  parts = data.split(":")
  if len(parts) != expected_parts:
    raise CallbackDataError(data)
  return parts


@router.message(Command("start"))
async def cmd_start(message: Message) -> None:
  state = load_state()
  remember_user(state, message.from_user)
  draft_set(state, int(message.from_user.id), None)
  save_state(state)
  await message.answer(START_TEXT, reply_markup=kb_main_menu())


@router.message(Command("help"))
@router.message(F.text == "❓ Помощь")
async def cmd_help(message: Message) -> None:
  await message.answer(HELP_TEXT, reply_markup=kb_main_menu())


@router.message(F.text == "🧹 Скрыть меню")
async def hide_menu(message: Message) -> None:
  await message.answer("Ок.", reply_markup=ReplyKeyboardRemove())


@router.message(F.text == "🎮 Создать игру")
async def menu_create_game(message: Message) -> None:
  state = load_state()
  remember_user(state, message.from_user)
  draft_set(state, int(message.from_user.id), {"mode": "create_game", "chat_id": int(message.chat.id)})
  save_state(state)
  await message.answer(
    "Кого пригласить?\n"
    "Отправь @username через пробел, например:\n"
    "@user1 @user2\n"
    "Или '-' если без приглашений."
  )


@router.message(Command("game"))
async def cmd_game(message: Message) -> None:
  _touch_user(message.from_user)
  invited_usernames = _unique_usernames(" ".join((message.text or "").split()[1:]))
  await create_lobby(message.bot, message.chat.id, message.from_user, invited_usernames)


@router.message(Command("end"))
async def cmd_end(message: Message) -> None:
  _touch_user(message.from_user)
  await request_finish(message.bot, message.chat.id, message.from_user.id)


async def _handle_lobby_callback(query: CallbackQuery, data: str) -> None:
  _, chat_str, lobby_id, action = _parse_exact(data, 4)
  lobby_chat_id = int(chat_str)
  uid = int(query.from_user.id)

  state = load_state()
  game = get_game(state, lobby_chat_id)
  if not game or game.get("id") != lobby_id:
    await query.answer("Игра не найдена")
    return

  host_id = int(game["host_id"])
  invited = game.get("invited_usernames") or []
  username = (query.from_user.username or "").lower()
  is_invited = (not invited) or (username in invited) or (uid == host_id)

  if action == "join":
    if game.get("stage") != "lobby":
      await query.answer("Лобби закрыто")
      return
    if not is_invited:
      await query.answer("Ты не в списке приглашенных")
      return
    players = game.setdefault("players", {})
    max_players = int(game["settings"]["players"])
    if str(uid) not in players:
      if len(players) >= max_players:
        await query.answer("Нет мест")
        return
      players[str(uid)] = {
        "name": query.from_user.full_name or "user",
        "username": (query.from_user.username or "").lower() or None,
      }
    set_game(state, lobby_chat_id, game)
    save_state(state)
    await sync_lobby_message(query.bot, lobby_chat_id)
    await query.answer("Ок")
    return

  if action == "leave":
    if game.get("stage") != "lobby":
      await query.answer("Лобби закрыто")
      return
    if uid == host_id:
      await query.answer("Хост не может выйти из лобби. Он может только отменить его.")
      return
    game.get("players", {}).pop(str(uid), None)
    set_game(state, lobby_chat_id, game)
    save_state(state)
    await sync_lobby_message(query.bot, lobby_chat_id)
    await query.answer("Ок")
    return

  if action == "start":
    if uid != host_id:
      await query.answer("Только хост")
      return
    await query.answer("Старт")
    await start_game(query.bot, lobby_chat_id)
    return

  if action == "cancel":
    if uid != host_id:
      await query.answer("Только хост")
      return
    message_id = game.get("lobby_message_id")
    if message_id:
      try:
        await query.bot.edit_message_text(
          "Игра отменена.",
          chat_id=lobby_chat_id,
          message_id=int(message_id),
          reply_markup=None,
        )
      except Exception:
        pass
    set_game(state, lobby_chat_id, None)
    save_state(state)
    await query.answer("Ок")
    return

  await query.answer("Неизвестное действие")


async def _handle_vote_callback(query: CallbackQuery, data: str) -> None:
  _, chat_str, choice = _parse_exact(data, 3)
  lobby_chat_id = int(chat_str)
  state = load_state()
  game = get_game(state, lobby_chat_id)
  if not game or game.get("stage") != "running":
    await query.answer("Игра не активна")
    return
  humans = game.get("humans", {})
  uid = int(query.from_user.id)
  if str(uid) not in humans:
    await query.answer("Ты не игрок")
    return
  vote = game.get("end_vote") or {}
  if not vote.get("active"):
    await query.answer("Голосование завершено")
    return

  yes_list = set(vote.get("yes", []))
  no_list = set(vote.get("no", []))
  yes_list.discard(uid)
  no_list.discard(uid)
  if choice == "yes":
    yes_list.add(uid)
  else:
    no_list.add(uid)
  vote["yes"] = list(yes_list)
  vote["no"] = list(no_list)

  human_count = int(vote.get("human_count", len(humans)))
  need = (human_count // 2) + 1
  yes_count = len(yes_list)
  no_count = len(no_list)

  game["end_vote"] = vote
  set_game(state, lobby_chat_id, game)
  save_state(state)

  await query.answer("Голос учтен")
  try:
    await query.message.edit_text(
      "🗳 Ваш голос учтен\n"
      f"Да: {yes_count}\n"
      f"Нет: {no_count}\n"
      f"Нужно Да: {need}",
      reply_markup=kb_finish_vote(lobby_chat_id),
    )
  except Exception:
    pass

  await query.bot.send_message(
    lobby_chat_id,
    "🗳 Обновление голосования\n"
    f"Да: {yes_count}\n"
    f"Нет: {no_count}\n"
    f"Нужно Да: {need}",
    reply_markup=kb_finish_vote(lobby_chat_id),
  )

  if yes_count >= need:
    vote["active"] = False
    if game.get("finishing"):
      await query.answer("Игра уже завершается")
      return
    game["end_vote"] = vote
    set_game(state, lobby_chat_id, game)
    save_state(state)
    gid = str(game.get("server_game_id"))
    await query.bot.send_message(lobby_chat_id, "Большинство набрано - завершаю игру.")
    await finish_game_now(query.bot, lobby_chat_id, gid)


async def _handle_end_callback(query: CallbackQuery, data: str) -> None:
  _, chat_str, uid_str = _parse_exact(data, 3)
  lobby_chat_id = int(chat_str)
  uid = int(uid_str)
  if int(query.from_user.id) != uid:
    await query.answer("Это не твоя кнопка")
    return
  await query.answer("Ок")
  await request_finish(query.bot, lobby_chat_id, uid)


async def _handle_goto_callback(query: CallbackQuery, data: str) -> None:
  raise CallbackDataError(data)


async def _handle_pet_target_callback(query: CallbackQuery, data: str) -> None:
  _, chat_str, uid_str = _parse_exact(data, 3)
  lobby_chat_id = int(chat_str)
  uid = int(uid_str)
  if int(query.from_user.id) != uid:
    await query.answer("Это не твоя кнопка")
    return
  state = load_state()
  game = get_game(state, lobby_chat_id)
  if not game or game.get("stage") != "running":
    await query.answer("Игра не активна")
    return
  gid = str(game.get("server_game_id"))
  player_state = api.player_state(gid, uid)
  targets = list(player_state.get("co_located_all") or [])
  my_role = game.get("humans", {}).get(str(uid))
  if my_role:
    targets = [name for name in targets if name != my_role]
  if not targets:
    await query.answer("Рядом нет игроков для обмена")
    return
  await query.bot.send_message(
    uid,
    "С кем обменяться питомцами?\n"
    "Игрок-человек должен подтвердить обмен.\n"
    "Бот согласится автоматически.",
    reply_markup=kb_pet_targets(lobby_chat_id, uid, targets),
  )
  await query.answer("Ок")


async def _handle_house_target_callback(query: CallbackQuery, data: str) -> None:
  _, chat_str, uid_str = _parse_exact(data, 3)
  lobby_chat_id = int(chat_str)
  uid = int(uid_str)
  if int(query.from_user.id) != uid:
    await query.answer("Это не твоя кнопка")
    return
  state = load_state()
  game = get_game(state, lobby_chat_id)
  if not game or game.get("stage") != "running":
    await query.answer("Игра не активна")
    return
  gid = str(game.get("server_game_id"))
  player_state = api.player_state(gid, uid)
  targets = list(player_state.get("all_roles") or [])
  if not targets:
    await query.answer("Нет доступных целей для обмена домами")
    return
  await query.bot.send_message(
    uid,
    "С кем обменяться домами?\n"
    "Игрок-человек должен подтвердить обмен.\n"
    "Бот согласится автоматически.",
    reply_markup=kb_house_targets(lobby_chat_id, uid, targets),
  )
  await query.answer("Ок")


async def _handle_action_callback(query: CallbackQuery, data: str) -> None:
  parts = data.split(":")
  if len(parts) not in (4, 5):
    raise CallbackDataError(data)
  _, chat_str, uid_str, kind = parts[:4]
  arg = parts[4] if len(parts) == 5 else None
  lobby_chat_id = int(chat_str)
  uid = int(uid_str)
  if int(query.from_user.id) != uid:
    await query.answer("Это не твоя кнопка")
    return
  state = load_state()
  game = get_game(state, lobby_chat_id)
  if not game or game.get("stage") != "running":
    await query.answer("Игра не активна")
    return
  humans = game.get("humans", {})
  if str(uid) not in humans:
    await query.answer("Ты не игрок")
    return
  gid = str(game.get("server_game_id"))

  try:
    if kind == "noop":
      pass
    elif kind == "go_to":
      if arg is None:
        await query.answer("Нет цели")
        return
      api.action(gid, uid, "go_to", dst=int(arg))
    elif kind in {"stay", "left", "right"}:
      api.action(gid, uid, kind)
    elif kind == "pet_offer":
      if arg is None:
        await query.answer("Нет цели")
        return
      api.action(gid, uid, "pet_offer", target=arg)
      if str(arg) in (game.get("role_to_uid") or {}):
        await notify_pet_offer(query.bot, lobby_chat_id, uid, str(arg))
      else:
        await query.bot.send_message(
          uid,
          f"🐾 Бот {arg} согласится автоматически. Обмен произойдет на следующем шаге, если вы останетесь в одном доме.",
        )
    elif kind == "house_offer":
      if arg is None:
        await query.answer("Нет цели")
        return
      api.action(gid, uid, "house_offer", target=arg)
      if str(arg) in (game.get("role_to_uid") or {}):
        await notify_house_offer(query.bot, lobby_chat_id, uid, str(arg))
      else:
        await query.bot.send_message(
          uid,
          f"🏠 Бот {arg} согласится автоматически. Обмен домами произойдет на следующем шаге, если вы останетесь в одном доме.",
        )
    elif kind == "pet_accept":
      if arg is None:
        await query.answer("Нет цели")
        return
      api.action(gid, uid, "pet_accept", target=arg)
      await notify_pet_answer(query.bot, lobby_chat_id, uid, str(arg), accepted=True)
    elif kind == "pet_decline":
      if arg is None:
        await query.answer("Нет цели")
        return
      api.action(gid, uid, "pet_decline", target=arg)
      await notify_pet_answer(query.bot, lobby_chat_id, uid, str(arg), accepted=False)
    elif kind == "house_accept":
      if arg is None:
        await query.answer("Нет цели")
        return
      api.action(gid, uid, "house_accept", target=arg)
      await notify_house_answer(query.bot, lobby_chat_id, uid, str(arg), accepted=True)
    elif kind == "house_decline":
      if arg is None:
        await query.answer("Нет цели")
        return
      api.action(gid, uid, "house_decline", target=arg)
      await notify_house_answer(query.bot, lobby_chat_id, uid, str(arg), accepted=False)
    else:
      await query.answer("Неизвестное действие")
      return
  except Exception as error:
    await query.answer(str(error)[:150])
    return

  await query.answer("Ок")
  await send_private_turn_state(query.bot, lobby_chat_id, uid)
  await maybe_step_and_next(query.bot, lobby_chat_id)


@router.callback_query()
async def on_cb(query: CallbackQuery) -> None:
  data = query.data or ""
  _touch_user(query.from_user)
  try:
    if data.startswith("l:"):
      await _handle_lobby_callback(query, data)
      return
    if data.startswith("v:"):
      await _handle_vote_callback(query, data)
      return
    if data.startswith("e:"):
      await _handle_end_callback(query, data)
      return
    if data.startswith("g:"):
      await _handle_goto_callback(query, data)
      return
    if data.startswith("p:"):
      await _handle_pet_target_callback(query, data)
      return
    if data.startswith("h:"):
      await _handle_house_target_callback(query, data)
      return
    if data.startswith("a:"):
      await _handle_action_callback(query, data)
      return
    await query.answer()
  except CallbackDataError:
    await query.answer("Некорректная кнопка")


@router.message()
async def catch_text_flow(message: Message) -> None:
  if not message.text or message.text.startswith("/") or not message.from_user:
    return
  state = load_state()
  remember_user(state, message.from_user)
  draft = draft_get(state, int(message.from_user.id))
  if not draft:
    save_state(state)
    return
  if draft.get("mode") != "create_game":
    draft_set(state, int(message.from_user.id), None)
    save_state(state)
    return

  lobby_chat_id = int(draft.get("chat_id", message.chat.id))
  invited_usernames: list[str] = []
  if message.text.strip() != "-":
    invited_usernames = _unique_usernames(message.text)

  draft_set(state, int(message.from_user.id), None)
  save_state(state)

  if message.chat.id != lobby_chat_id:
    await message.answer("Создай игру в том чате, где будет сцена, и нажми 'Создать игру' там.")
    return
  await create_lobby(message.bot, message.chat.id, message.from_user, invited_usernames)
