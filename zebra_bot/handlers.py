from __future__ import annotations

from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message, ReplyKeyboardRemove

from zebra_bot.keyboards import kb_main_menu, kb_goto_page, kb_pet_targets
from zebra_bot.storage import (
  load_state,
  save_state,
  remember_user,
  draft_get,
  draft_set,
  get_game,
  set_game,
)
from zebra_bot import api
from zebra_bot.game_flow import (
  create_lobby,
  sync_lobby_message,
  start_game,
  request_finish,
  send_private_turn_state,
  maybe_step_and_next,
  notify_pet_offer,
  notify_pet_answer,
)


router = Router()


@router.message(Command("start"))
async def cmd_start(m: Message) -> None:
  state = load_state()
  remember_user(state, m.from_user)
  draft_set(state, int(m.from_user.id), None)
  save_state(state)

  text = (
    "🎮 ZEBRA\n"
    "Схема: группа - сцена, личка - приватные ходы.\n"
    "Чтобы приглашения/приватные ходы работали, нужно 1 раз нажать /start в личке."
  )
  await m.answer(text, reply_markup=kb_main_menu())


@router.message(Command("help"))
@router.message(F.text == "❓ Помощь")
async def cmd_help(m: Message) -> None:
  text = (
    "🎮 Создать игру - создаст лобби в этом чате.\n"
    "Дальше игроки жмут Join.\n\n"
    "Команды:\n"
    "/game @user1 @user2 ...\n"
    "/end"
  )
  await m.answer(text, reply_markup=kb_main_menu())


@router.message(F.text == "🧹 Скрыть меню")
async def hide_menu(m: Message) -> None:
  await m.answer("Ок.", reply_markup=ReplyKeyboardRemove())


@router.message(F.text == "🎮 Создать игру")
async def menu_create_game(m: Message) -> None:
  state = load_state()
  remember_user(state, m.from_user)
  draft_set(state, int(m.from_user.id), {"mode": "create_game", "chat_id": int(m.chat.id)})
  save_state(state)

  await m.answer(
    "Кого пригласить?\n"
    "Отправь @username через пробел, например:\n"
    "@user1 @user2\n"
    "Или '-' если без приглашений."
  )


@router.message(Command("game"))
async def cmd_game(m: Message) -> None:
  state = load_state()
  remember_user(state, m.from_user)
  save_state(state)

  invited_usernames: list[str] = []
  parts = (m.text or "").split()
  for t in parts[1:]:
    if t.startswith("@") and len(t) > 1:
      invited_usernames.append(t[1:].lower())
  invited_usernames = list(dict.fromkeys(invited_usernames))

  await create_lobby(m.bot, m.chat.id, m.from_user, invited_usernames)


@router.message(Command("end"))
async def cmd_end(m: Message) -> None:
  state = load_state()
  remember_user(state, m.from_user)
  save_state(state)
  await request_finish(m.bot, m.chat.id, m.from_user.id)


@router.callback_query()
async def on_cb(q: CallbackQuery) -> None:
  data = q.data or ""

  state = load_state()
  remember_user(state, q.from_user)
  save_state(state)

  if data.startswith("l:"):
    parts = data.split(":")
    if len(parts) != 4:
      await q.answer()
      return
    _, chat_str, lobby_id, action = parts
    lobby_chat_id = int(chat_str)

    state = load_state()
    game = get_game(state, lobby_chat_id)
    if not game or game.get("id") != lobby_id:
      await q.answer("Игра не найдена")
      return

    host_id = int(game["host_id"])
    uid = int(q.from_user.id)

    invited = game.get("invited_usernames") or []
    u_name = (q.from_user.username or "").lower()
    is_invited = (not invited) or (u_name in invited) or (uid == host_id)

    if action == "join":
      if game.get("stage") != "lobby":
        await q.answer("Лобби закрыто")
        return
      if not is_invited:
        await q.answer("Ты не в списке приглашенных")
        return
      players = game.setdefault("players", {})
      need = int(game["settings"]["players"])
      if str(uid) not in players:
        if len(players) >= need:
          await q.answer("Нет мест")
          return
        players[str(uid)] = {
          "name": q.from_user.full_name or "user",
          "username": (q.from_user.username or "").lower() or None,
        }
      set_game(state, lobby_chat_id, game)
      save_state(state)
      await sync_lobby_message(q.bot, lobby_chat_id)
      await q.answer("Ок")
      return

    if action == "leave":
      if game.get("stage") != "lobby":
        await q.answer("Лобби закрыто")
        return
      if uid == host_id:
        await q.answer("Хост не может выйти. Cancel.")
        return
      game.get("players", {}).pop(str(uid), None)
      set_game(state, lobby_chat_id, game)
      save_state(state)
      await sync_lobby_message(q.bot, lobby_chat_id)
      await q.answer("Ок")
      return

    if action == "start":
      if uid != host_id:
        await q.answer("Только хост")
        return
      await q.answer("Старт")
      await start_game(q.bot, lobby_chat_id)
      return

    if action == "cancel":
      if uid != host_id:
        await q.answer("Только хост")
        return
      set_game(state, lobby_chat_id, None)
      save_state(state)
      await sync_lobby_message(q.bot, lobby_chat_id, force_text="Игра отменена.")
      await q.answer("Ок")
      return

  if data.startswith("v:"):
    parts = data.split(":")
    if len(parts) != 3:
      await q.answer()
      return
    _, chat_str, choice = parts
    lobby_chat_id = int(chat_str)

    state = load_state()
    game = get_game(state, lobby_chat_id)
    if not game or game.get("stage") != "running":
      await q.answer("Игра не активна")
      return

    humans = game.get("humans", {})
    if str(q.from_user.id) not in humans:
      await q.answer("Ты не игрок")
      return

    vote = game.get("end_vote") or {}
    if not vote.get("active"):
      await q.answer("Голосование завершено")
      return

    yes_list = set(vote.get("yes", []))
    no_list = set(vote.get("no", []))
    uid = int(q.from_user.id)
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
    yes_cnt = len(yes_list)

    game["end_vote"] = vote
    set_game(state, lobby_chat_id, game)
    save_state(state)

    if yes_cnt >= need:
      vote["active"] = False
      game["end_vote"] = vote
      set_game(state, lobby_chat_id, game)
      save_state(state)
      await q.answer("Большинство набрано")
      await q.bot.send_message(lobby_chat_id, "Большинство набрано - завершаю игру.")
      await request_finish(q.bot, lobby_chat_id, q.from_user.id)
      return

    await q.answer(f"Голос учтен: YES={yes_cnt}/{need}")
    return

  if data.startswith("e:"):
    _, chat_str, uid_str = data.split(":")
    lobby_chat_id = int(chat_str)
    uid = int(uid_str)
    if int(q.from_user.id) != uid:
      await q.answer("Это не твоя кнопка")
      return
    await q.answer("Ок")
    await request_finish(q.bot, lobby_chat_id, uid)
    return

  if data.startswith("g:"):
    _, chat_str, uid_str, page_str = data.split(":")
    lobby_chat_id = int(chat_str)
    uid = int(uid_str)
    page = int(page_str)
    if int(q.from_user.id) != uid:
      await q.answer("Это не твоя кнопка")
      return
    state = load_state()
    game = get_game(state, lobby_chat_id)
    if not game or game.get("stage") != "running":
      await q.answer("Игра не активна")
      return
    gid = str(game.get("server_game_id"))
    ps = api.player_state(gid, uid)
    houses = int(game["settings"]["houses"])
    cur = int(ps.get("location", 1))
    await q.bot.send_message(uid, f"Выбор дома (страница {page})", reply_markup=kb_goto_page(lobby_chat_id, uid, houses, page, cur))
    await q.answer("Ок")
    return

  if data.startswith("p:"):
    _, chat_str, uid_str = data.split(":")
    lobby_chat_id = int(chat_str)
    uid = int(uid_str)
    if int(q.from_user.id) != uid:
      await q.answer("Это не твоя кнопка")
      return
    state = load_state()
    game = get_game(state, lobby_chat_id)
    if not game or game.get("stage") != "running":
      await q.answer("Игра не активна")
      return
    gid = str(game.get("server_game_id"))
    ps = api.player_state(gid, uid)
    targets = ps.get("co_located_humans") or []
    if not targets:
      await q.answer("Нет живых игроков рядом")
      return
    await q.bot.send_message(uid, "С кем обменяться питомцами? (нужно согласие второго игрока)", reply_markup=kb_pet_targets(lobby_chat_id, uid, targets))
    await q.answer("Ок")
    return

  if data.startswith("a:"):
    parts = data.split(":")
    if len(parts) not in (4, 5):
      await q.answer()
      return
    _, chat_str, uid_str, kind = parts[:4]
    arg = parts[4] if len(parts) == 5 else None
    lobby_chat_id = int(chat_str)
    uid = int(uid_str)
    if int(q.from_user.id) != uid:
      await q.answer("Это не твоя кнопка")
      return

    state = load_state()
    game = get_game(state, lobby_chat_id)
    if not game or game.get("stage") != "running":
      await q.answer("Игра не активна")
      return

    gid = str(game.get("server_game_id"))
    humans = game.get("humans", {})
    if str(uid) not in humans:
      await q.answer("Ты не игрок")
      return

    try:
      if kind == "noop":
        pass
      elif kind == "go_to":
        api.action(gid, uid, "go_to", dst=int(arg))
      elif kind in ("stay", "left", "right"):
        api.action(gid, uid, kind)
      elif kind == "pet_offer":
        api.action(gid, uid, "pet_offer", target=arg)
        await notify_pet_offer(q.bot, lobby_chat_id, uid, str(arg))
      elif kind == "pet_accept":
        api.action(gid, uid, "pet_accept", target=arg)
        await notify_pet_answer(q.bot, lobby_chat_id, uid, str(arg), accepted=True)
      elif kind == "pet_decline":
        api.action(gid, uid, "pet_decline", target=arg)
        await notify_pet_answer(q.bot, lobby_chat_id, uid, str(arg), accepted=False)
      else:
        await q.answer("Неизвестное действие")
        return

      await q.answer("Ок")
      await send_private_turn_state(q.bot, lobby_chat_id, uid)
      await maybe_step_and_next(q.bot, lobby_chat_id)
    except Exception:
      await q.answer("Ошибка")
    return

  await q.answer()


@router.message()
async def catch_text_flow(m: Message) -> None:
  if not m.text or m.text.startswith("/"):
    return
  if not m.from_user:
    return

  state = load_state()
  remember_user(state, m.from_user)

  draft = draft_get(state, int(m.from_user.id))
  if not draft:
    save_state(state)
    return

  mode = draft.get("mode")
  if mode != "create_game":
    draft_set(state, int(m.from_user.id), None)
    save_state(state)
    return

  lobby_chat_id = int(draft.get("chat_id", m.chat.id))
  raw = m.text.strip()

  invited_usernames: list[str] = []
  if raw != "-":
    for t in raw.split():
      if t.startswith("@") and len(t) > 1:
        invited_usernames.append(t[1:].lower())
  invited_usernames = list(dict.fromkeys(invited_usernames))

  draft_set(state, int(m.from_user.id), None)
  save_state(state)

  if m.chat.id != lobby_chat_id:
    await m.answer("Создай игру в том чате, где будет сцена (группа), и нажми 'Создать игру' там.")
    return

  await create_lobby(m.bot, m.chat.id, m.from_user, invited_usernames)
