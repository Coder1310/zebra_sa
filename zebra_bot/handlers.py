from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message, ReplyKeyboardRemove

from zebra_bot import api
from zebra_bot.game_flow import (
  create_lobby,
  maybe_step_and_next,
  notify_pet_answer,
  notify_pet_offer,
  request_finish,
  send_private_turn_state,
  start_game,
  sync_lobby_message,
)
from zebra_bot.keyboards import kb_goto_page, kb_main_menu, kb_pet_targets
from zebra_bot.storage import (
  draft_get,
  draft_set,
  get_game,
  load_state,
  remember_user,
  save_state,
  set_game,
)


router = Router()


@router.message(Command("start"))
async def cmd_start(message: Message) -> None:
  state = load_state()
  remember_user(state, message.from_user)
  draft_set(state, int(message.from_user.id), None)
  save_state(state)

  text = (
    "🎮 ZEBRA\n"
    "Схема: группа - сцена, личка - приватные ходы.\n"
    "Чтобы приглашения и приватные ходы работали, нужно один раз нажать /start в личке."
  )
  await message.answer(text, reply_markup = kb_main_menu())


@router.message(Command("help"))
@router.message(F.text == "❓ Помощь")
async def cmd_help(message: Message) -> None:
  text = (
    "🎮 Создать игру - создаст лобби в этом чате.\n"
    "Дальше игроки жмут Join.\n\n"
    "Команды:\n"
    "/game @user1 @user2 ...\n"
    "/end"
  )
  await message.answer(text, reply_markup = kb_main_menu())


@router.message(F.text == "🧹 Скрыть меню")
async def hide_menu(message: Message) -> None:
  await message.answer("Ок.", reply_markup = ReplyKeyboardRemove())


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
  state = load_state()
  remember_user(state, message.from_user)
  save_state(state)

  invited_usernames: list[str] = []
  for token in (message.text or "").split()[1:]:
    if token.startswith("@") and len(token) > 1:
      invited_usernames.append(token[1:].lower())
  invited_usernames = list(dict.fromkeys(invited_usernames))

  await create_lobby(message.bot, message.chat.id, message.from_user, invited_usernames)


@router.message(Command("end"))
async def cmd_end(message: Message) -> None:
  state = load_state()
  remember_user(state, message.from_user)
  save_state(state)
  await request_finish(message.bot, message.chat.id, message.from_user.id)


@router.callback_query()
async def on_cb(query: CallbackQuery) -> None:
  data = query.data or ""

  state = load_state()
  remember_user(state, query.from_user)
  save_state(state)

  if data.startswith("l:"):
    _, chat_str, lobby_id, action = data.split(":")
    lobby_chat_id = int(chat_str)

    state = load_state()
    game = get_game(state, lobby_chat_id)
    if not game or game.get("id") != lobby_id:
      await query.answer("Игра не найдена")
      return

    host_id = int(game["host_id"])
    uid = int(query.from_user.id)
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
      need = int(game["settings"]["players"])
      if str(uid) not in players:
        if len(players) >= need:
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
            chat_id = lobby_chat_id,
            message_id = int(message_id),
            reply_markup = None,
          )
        except Exception:
          pass

      set_game(state, lobby_chat_id, None)
      save_state(state)
      await query.answer("Ок")
      return

  if data.startswith("v:"):
    _, chat_str, choice = data.split(":")
    lobby_chat_id = int(chat_str)

    state = load_state()
    game = get_game(state, lobby_chat_id)
    if not game or game.get("stage") != "running":
      await query.answer("Игра не активна")
      return

    humans = game.get("humans", {})
    if str(query.from_user.id) not in humans:
      await query.answer("Ты не игрок")
      return

    vote = game.get("end_vote") or {}
    if not vote.get("active"):
      await query.answer("Голосование завершено")
      return

    yes_list = set(vote.get("yes", []))
    no_list = set(vote.get("no", []))
    uid = int(query.from_user.id)
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

    game["end_vote"] = vote
    set_game(state, lobby_chat_id, game)
    save_state(state)

    if yes_count >= need:
      vote["active"] = False
      game["end_vote"] = vote
      set_game(state, lobby_chat_id, game)
      save_state(state)
      await query.answer("Большинство набрано")
      await query.bot.send_message(lobby_chat_id, "Большинство набрано - завершаю игру.")
      await request_finish(query.bot, lobby_chat_id, query.from_user.id)
      return

    await query.answer(f"Голос учтен: YES={yes_count}/{need}")
    return

  if data.startswith("e:"):
    _, chat_str, uid_str = data.split(":")
    lobby_chat_id = int(chat_str)
    uid = int(uid_str)
    if int(query.from_user.id) != uid:
      await query.answer("Это не твоя кнопка")
      return
    await query.answer("Ок")
    await request_finish(query.bot, lobby_chat_id, uid)
    return

  if data.startswith("g:"):
    _, chat_str, uid_str, page_str = data.split(":")
    lobby_chat_id = int(chat_str)
    uid = int(uid_str)
    page = int(page_str)
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
    houses = int(game["settings"]["houses"])
    current = int(player_state.get("location", 1))
    await query.bot.send_message(
      uid,
      f"Выбор дома (страница {page})",
      reply_markup = kb_goto_page(lobby_chat_id, uid, houses, page, current),
    )
    await query.answer("Ок")
    return

  if data.startswith("p:"):
    _, chat_str, uid_str = data.split(":")
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
    targets = player_state.get("co_located_humans") or []
    if not targets:
      await query.answer("Нет живых игроков рядом")
      return

    await query.bot.send_message(
      uid,
      "С кем обменяться питомцами? Нужно согласие второго игрока.",
      reply_markup = kb_pet_targets(lobby_chat_id, uid, targets),
    )
    await query.answer("Ок")
    return

  if data.startswith("a:"):
    parts = data.split(":")
    if len(parts) not in (4, 5):
      await query.answer()
      return

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

    gid = str(game.get("server_game_id"))
    humans = game.get("humans", {})
    if str(uid) not in humans:
      await query.answer("Ты не игрок")
      return

    try:
      if kind == "noop":
        pass
      elif kind == "go_to":
        api.action(gid, uid, "go_to", dst = int(arg))
      elif kind in ("stay", "left", "right"):
        api.action(gid, uid, kind)
      elif kind == "pet_offer":
        api.action(gid, uid, "pet_offer", target = arg)
        await notify_pet_offer(query.bot, lobby_chat_id, uid, str(arg))
      elif kind == "pet_accept":
        api.action(gid, uid, "pet_accept", target = arg)
        await notify_pet_answer(query.bot, lobby_chat_id, uid, str(arg), accepted = True)
      elif kind == "pet_decline":
        api.action(gid, uid, "pet_decline", target = arg)
        await notify_pet_answer(query.bot, lobby_chat_id, uid, str(arg), accepted = False)
      else:
        await query.answer("Неизвестное действие")
        return

      await query.answer("Ок")
      await send_private_turn_state(query.bot, lobby_chat_id, uid)
      await maybe_step_and_next(query.bot, lobby_chat_id)
    except Exception:
      await query.answer("Ошибка")
    return

  await query.answer()


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
  raw = message.text.strip()
  invited_usernames: list[str] = []
  if raw != "-":
    for token in raw.split():
      if token.startswith("@") and len(token) > 1:
        invited_usernames.append(token[1:].lower())
  invited_usernames = list(dict.fromkeys(invited_usernames))

  draft_set(state, int(message.from_user.id), None)
  save_state(state)

  if message.chat.id != lobby_chat_id:
    await message.answer("Создай игру в том чате, где будет сцена, и нажми 'Создать игру' там.")
    return

  await create_lobby(message.bot, message.chat.id, message.from_user, invited_usernames)