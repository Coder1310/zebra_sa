from __future__ import annotations

import asyncio
import random
import time
import zipfile
from pathlib import Path
from typing import Any

from aiogram import Bot
from aiogram.types import FSInputFile

from zebra_bot import api
from zebra_bot.config import DEFAULTS, LOGS_DIR, defaults_dict
from zebra_bot.keyboards import (
  kb_actions_for_player,
  kb_finish_vote,
  kb_house_offer_answer,
  kb_lobby,
  kb_pet_offer_answer,
)
from simulator.world import roles_for
from zebra_bot.render import format_lobby, render_player_info
from zebra_bot.storage import get_game, load_state, mention, save_state, set_game, user_id_by_username


def _zip_files(zip_path: Path, paths: list[Path]) -> None:
  zip_path.parent.mkdir(parents=True, exist_ok=True)
  with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as archive:
    for path in paths:
      if path.exists():
        archive.write(path, arcname=path.name)


def _archive_paths(files: dict[str, str]) -> list[Path]:
  ordered_keys = ["metrics", "metrics_ext", "csv", "xml"]
  paths: list[Path] = []
  for key in ordered_keys:
    raw_path = files.get(key)
    if raw_path:
      paths.append(Path(raw_path))
  return paths


def _is_lobby(game: dict[str, Any] | None) -> bool:
  return bool(game and game.get("stage") == "lobby")


def _is_running(game: dict[str, Any] | None) -> bool:
  return bool(game and game.get("stage") == "running")


async def _send_dm(bot: Bot, uid: int, text: str, reply_markup: Any | None = None) -> bool:
  try:
    await bot.send_message(uid, text, reply_markup=reply_markup)
    return True
  except Exception:
    return False


async def _send_dm_document(bot: Bot, uid: int, path: Path) -> bool:
  try:
    await bot.send_document(uid, FSInputFile(str(path)))
    return True
  except Exception:
    return False


async def sync_lobby_message(bot: Bot, lobby_chat_id: int, force_text: str | None = None) -> None:
  state = load_state()
  game = get_game(state, lobby_chat_id)
  if not game:
    return

  message_id = game.get("lobby_message_id")
  if not message_id:
    return

  text = force_text or format_lobby(game)
  reply_markup = kb_lobby(lobby_chat_id, str(game["id"])) if game.get("stage") == "lobby" else None

  try:
    await bot.edit_message_text(text, chat_id=lobby_chat_id, message_id=int(message_id), reply_markup=reply_markup)
    return
  except Exception:
    pass

  try:
    message = await bot.send_message(lobby_chat_id, text, reply_markup=reply_markup)
  except Exception:
    return

  state = load_state()
  game = get_game(state, lobby_chat_id)
  if not game:
    return
  game["lobby_message_id"] = int(message.message_id)
  set_game(state, lobby_chat_id, game)
  save_state(state)


async def create_lobby(bot: Bot, lobby_chat_id: int, host_user: Any, invited_usernames: list[str]) -> None:
  state = load_state()
  existing = get_game(state, lobby_chat_id)
  if existing:
    if existing.get("stage") == "lobby":
      await bot.send_message(lobby_chat_id, "В этом чате уже есть лобби. Хост может отменить его кнопкой Cancel.")
    else:
      await bot.send_message(lobby_chat_id, "В этом чате уже идет игра.")
    return

  settings = defaults_dict()
  lobby_id = str(int(time.time()))
  invited: list[str] = []
  seen: set[str] = set()
  for username in invited_usernames:
    name = username.strip().lstrip("@").lower()
    if not name or name in seen:
      continue
    seen.add(name)
    invited.append(name)

  game = {
    "id": lobby_id,
    "chat_id": int(lobby_chat_id),
    "host_id": int(host_user.id),
    "created_at": int(time.time()),
    "deadline_at": time.time() + int(settings["lobby_delay_sec"]),
    "stage": "lobby",
    "settings": settings,
    "invited_usernames": invited,
    "players": {
      str(host_user.id): {
        "name": host_user.full_name or "host",
        "username": (host_user.username or "").lower() or None,
      }
    },
  }
  set_game(state, lobby_chat_id, game)
  save_state(state)

  message = await bot.send_message(lobby_chat_id, format_lobby(game), reply_markup=kb_lobby(lobby_chat_id, lobby_id))
  state = load_state()
  game = get_game(state, lobby_chat_id) or game
  game["lobby_message_id"] = int(message.message_id)
  set_game(state, lobby_chat_id, game)
  save_state(state)

  if invited:
    missing_users: list[str] = []
    for username in invited:
      uid = user_id_by_username(state, username)
      if uid is None:
        missing_users.append(username)
        continue
      await _send_dm(
        bot,
        uid,
        f"🎮 Тебя пригласили в игру ZEBRA.\nЛобби в чате {lobby_chat_id}.\nНажми Join.",
        reply_markup=kb_lobby(lobby_chat_id, lobby_id),
      )
    if missing_users:
      await bot.send_message(
        lobby_chat_id,
        "Не смог отправить приглашение (эти пользователи не нажимали /start боту): "
        + " ".join(f"@{name}" for name in missing_users),
      )

  asyncio.create_task(_auto_start_lobby(bot, lobby_chat_id, lobby_id, int(settings["lobby_delay_sec"]) + 1))


async def _auto_start_lobby(bot: Bot, lobby_chat_id: int, lobby_id: str, delay_sec: int) -> None:
  await asyncio.sleep(delay_sec)
  state = load_state()
  game = get_game(state, lobby_chat_id)
  if not _is_lobby(game) or str(game.get("id")) != lobby_id:
    return
  await start_game(bot, lobby_chat_id)


async def start_game(bot: Bot, lobby_chat_id: int) -> None:
  state = load_state()
  game = get_game(state, lobby_chat_id)
  if not _is_lobby(game):
    return

  players = list((game.get("players") or {}).items())
  need = int(game["settings"]["players"])
  houses = int(game["settings"]["houses"])

  roles = roles_for(need, houses)
  rng = random.Random(int(game.get("created_at", time.time())))
  rng.shuffle(roles)

  humans = players[:need]
  humans_map: dict[str, str] = {}
  role_to_uid: dict[str, str] = {}

  for index, (uid_str, payload) in enumerate(humans):
    role = roles[index]
    uid = str(uid_str)
    humans_map[uid] = role
    role_to_uid[role] = uid

  cfg = {
    "cfg": {
      "agents": need,
      "houses": houses,
      "days": int(game["settings"]["days"]),
      "share": str(game["settings"]["share"]),
      "noise": float(game["settings"]["noise"]),
      "seed": None,
      "graph": str(game["settings"]["graph"]),
    },
    "humans": {int(uid): role for uid, role in humans_map.items()},
  }

  await bot.send_message(lobby_chat_id, "🎮 Создаю игровую сессию на сервере...")
  try:
    gid = api.create_game(cfg)
  except Exception as error:
    await bot.send_message(lobby_chat_id, f"Не удалось создать игру на сервере: {error}")
    return

  game["stage"] = "running"
  game["server_game_id"] = gid
  game["humans"] = humans_map
  game["role_to_uid"] = role_to_uid
  game["end_vote"] = None
  set_game(state, lobby_chat_id, game)
  save_state(state)

  message_id = game.get("lobby_message_id")
  if message_id:
    try:
      await bot.edit_message_reply_markup(chat_id=lobby_chat_id, message_id=int(message_id), reply_markup=None)
    except Exception:
      pass

  await bot.send_message(
    lobby_chat_id,
    "🎮 Игра началась.\n"
    "Роли игроков скрыты.\n"
    "Ходы и приватные сообщения приходят в личку.",
  )

  for uid_str in humans_map:
    uid = int(uid_str)
    sent = await send_private_turn_state(bot, lobby_chat_id, uid)
    if not sent:
      player = game["players"].get(uid_str, {"name": "user"})
      await bot.send_message(lobby_chat_id, f"⚠ Не смог написать в личку {mention(player)}. Пусть он откроет бота и нажмет /start.")

  await send_group_waiting(bot, lobby_chat_id)
  asyncio.create_task(turn_timer(bot, lobby_chat_id))


async def send_private_turn_state(bot: Bot, lobby_chat_id: int, uid: int) -> bool:
  state = load_state()
  game = get_game(state, lobby_chat_id)
  if not _is_running(game):
    return False
  gid = str(game.get("server_game_id"))
  try:
    player_state = api.player_state(gid, uid)
  except Exception:
    return False
  text = render_player_info(player_state)
  markup = kb_actions_for_player(lobby_chat_id, uid, player_state)
  return await _send_dm(bot, uid, text, reply_markup=markup)


async def send_group_waiting(bot: Bot, lobby_chat_id: int) -> None:
  state = load_state()
  game = get_game(state, lobby_chat_id)
  if not _is_running(game):
    return
  gid = str(game.get("server_game_id"))
  try:
    current_state = api.state(gid)
  except Exception:
    await bot.send_message(lobby_chat_id, "Не удалось получить состояние игры.")
    return
  pending = list(current_state.get("pending_user_ids") or [])
  if not pending:
    await bot.send_message(lobby_chat_id, "⏳ Сейчас никто не должен ходить.")
    return
  players = game.get("players") or {}
  names = [mention(players.get(str(uid), {"name": str(uid)})) for uid in pending]
  await bot.send_message(lobby_chat_id, "⏳ Ожидаю ходы от: " + ", ".join(names))


async def turn_timer(bot: Bot, lobby_chat_id: int) -> None:
  while True:
    await asyncio.sleep(int(DEFAULTS.turn_delay_sec))
    state = load_state()
    game = get_game(state, lobby_chat_id)
    if not _is_running(game):
      return
    gid = str(game.get("server_game_id"))
    try:
      current_state = api.state(gid)
    except Exception:
      return
    pending = list(current_state.get("pending_user_ids") or [])

    any_trip = False
    for uid_str in (game.get("humans") or {}).keys():
      uid = int(uid_str)
      try:
        player_state = api.player_state(gid, uid)
      except Exception:
        continue
      trip = player_state.get("trip") or {}
      if player_state.get("ok") and bool(trip.get("active")):
        any_trip = True
        break

    if pending or any_trip:
      await do_step_and_next(bot, lobby_chat_id)


async def maybe_step_and_next(bot: Bot, lobby_chat_id: int) -> None:
  state = load_state()
  game = get_game(state, lobby_chat_id)
  if not _is_running(game):
    return
  gid = str(game.get("server_game_id"))
  try:
    current_state = api.state(gid)
  except Exception:
    await bot.send_message(lobby_chat_id, "Не удалось получить состояние игры.")
    return
  if len(current_state.get("pending_user_ids") or []) == 0:
    await do_step_and_next(bot, lobby_chat_id)
  else:
    await send_group_waiting(bot, lobby_chat_id)


async def do_step_and_next(bot: Bot, lobby_chat_id: int) -> None:
  state = load_state()
  game = get_game(state, lobby_chat_id)
  if not _is_running(game) or game.get("finishing"):
    return
  gid = str(game.get("server_game_id"))
  try:
    result = api.step(gid)
  except Exception as error:
    await bot.send_message(lobby_chat_id, f"Ошибка при шаге игры: {error}")
    return

  day_finished = result.get("day_finished")
  if day_finished is not None:
    await bot.send_message(lobby_chat_id, f"✅ День {day_finished} завершен.")

  reports = result.get("reports") or {}
  for uid_str, role in (game.get("humans") or {}).items():
    uid = int(uid_str)
    lines = reports.get(role) or []
    if lines:
      await _send_dm(bot, uid, "\n".join(lines))

  if result.get("done"):
    await finish_game_now(bot, lobby_chat_id, gid)
    return

  for uid_str in (game.get("humans") or {}).keys():
    await send_private_turn_state(bot, lobby_chat_id, int(uid_str))
  await send_group_waiting(bot, lobby_chat_id)


async def finish_game_now(bot: Bot, lobby_chat_id: int, gid: str) -> None:
  state = load_state()
  game = get_game(state, lobby_chat_id)
  if not _is_running(game):
    return
  if game.get("finishing"):
    return
  game["finishing"] = True
  set_game(state, lobby_chat_id, game)
  save_state(state)
  try:
    result = api.finish(gid)
  except Exception as error:
    state = load_state()
    game = get_game(state, lobby_chat_id)
    if game:
      game.pop("finishing", None)
      set_game(state, lobby_chat_id, game)
      save_state(state)
    await bot.send_message(lobby_chat_id, f"Не удалось завершить игру на сервере: {error}")
    return

  lines: list[str] = []
  day_finished = result.get("day_finished")
  if day_finished is None:
    lines.append("🏁 Игра завершена. Топ M1:")
  else:
    lines.append(f"🏁 Игра завершена на дне {day_finished}. Топ M1:")
  for index, item in enumerate(result.get("leaderboard") or [], start=1):
    try:
      lines.append(f"{index}) {item[0]}: {float(item[1]):.3f}")
    except Exception:
      continue
  summary_text = "\n".join(lines)
  await bot.send_message(lobby_chat_id, summary_text)

  files = result.get("files") or {}
  archive_paths = _archive_paths(files)
  zip_path: Path | None = None
  if archive_paths:
    zip_path = LOGS_DIR / f"game_{gid}.zip"
    _zip_files(zip_path, archive_paths)
    try:
      await bot.send_document(lobby_chat_id, FSInputFile(str(zip_path)))
    except Exception:
      await bot.send_message(lobby_chat_id, "Не смог отправить архив в группу.")

  humans = game.get("humans") or {}
  failed_dm: list[str] = []
  # In a solo game the only human already sees the summary and archive in the group,
  # so sending the same result to their DM looks like a duplicate.
  if len(humans) > 1:
    for uid_str in humans.keys():
      uid = int(uid_str)
      player = game.get("players", {}).get(uid_str, {"name": uid_str})
      sent_text = await _send_dm(bot, uid, summary_text)
      if not sent_text:
        failed_dm.append(mention(player))
        continue
      if zip_path is not None:
        sent_doc = await _send_dm_document(bot, uid, zip_path)
        if not sent_doc:
          failed_dm.append(mention(player))

  if failed_dm:
    await bot.send_message(lobby_chat_id, "Не смог отправить итог или архив в личку этим игрокам: " + ", ".join(failed_dm))

  state = load_state()
  set_game(state, lobby_chat_id, None)
  save_state(state)


async def _broadcast_vote_prompt(bot: Bot, lobby_chat_id: int, game: dict[str, Any]) -> None:
  vote = game.get("end_vote") or {}
  if not vote.get("active"):
    return
  humans = game.get("humans") or {}
  players = game.get("players") or {}
  human_count = int(vote.get("human_count", len(humans)))
  need = (human_count // 2) + 1
  yes_count = len(set(vote.get("yes") or []))
  no_count = len(set(vote.get("no") or []))
  requester_id = int(vote.get("requester_id", 0)) if vote.get("requester_id") is not None else 0
  requester_name = mention(players.get(str(requester_id), {"id": requester_id}))
  group_text = (
    "🗳 Идет голосование за завершение игры\n"
    f"Инициатор: {requester_name}\n"
    f"Да: {yes_count}\n"
    f"Нет: {no_count}\n"
    f"Нужно голосов Да: {need}"
  )
  await bot.send_message(lobby_chat_id, group_text, reply_markup=kb_finish_vote(lobby_chat_id))

  failed: list[str] = []
  for uid_str in humans.keys():
    uid = int(uid_str)
    user_row = players.get(uid_str, {"id": uid})
    dm_text = (
      "🗳 Идет голосование за завершение игры\n"
      f"Инициатор: {requester_name}\n"
      f"Да: {yes_count}\n"
      f"Нет: {no_count}\n"
      f"Нужно голосов Да: {need}\n\n"
      "Нажмите кнопку ниже."
    )
    sent = await _send_dm(bot, uid, dm_text, reply_markup=kb_finish_vote(lobby_chat_id))
    if not sent:
      failed.append(mention(user_row))
  if failed:
    await bot.send_message(lobby_chat_id, "Не удалось отправить личное сообщение этим игрокам: " + ", ".join(failed))


async def request_finish(bot: Bot, lobby_chat_id: int, requester_id: int) -> None:
  state = load_state()
  game = get_game(state, lobby_chat_id)
  if not _is_running(game):
    await bot.send_message(lobby_chat_id, "Игра не активна.")
    return
  if game.get("finishing"):
    await bot.send_message(lobby_chat_id, "Игра уже завершается.")
    return
  gid = game.get("server_game_id")
  if not gid:
    await bot.send_message(lobby_chat_id, "Игра еще не создана.")
    return
  humans = game.get("humans") or {}
  human_count = len(humans)
  if human_count <= 1:
    await bot.send_message(lobby_chat_id, "Живой игрок один - завершаю игру.")
    await finish_game_now(bot, lobby_chat_id, str(gid))
    return

  vote = game.get("end_vote") or {}
  if vote.get("active"):
    await bot.send_message(lobby_chat_id, "Голосование уже идет.")
    await _broadcast_vote_prompt(bot, lobby_chat_id, game)
    return

  game["end_vote"] = {
    "active": True,
    "yes": [int(requester_id)],
    "no": [],
    "deadline_at": time.time() + int(DEFAULTS.vote_delay_sec),
    "human_count": human_count,
    "requester_id": int(requester_id),
  }
  set_game(state, lobby_chat_id, game)
  save_state(state)
  await _broadcast_vote_prompt(bot, lobby_chat_id, game)
  asyncio.create_task(_vote_timer(bot, lobby_chat_id, str(gid)))


async def _vote_timer(bot: Bot, lobby_chat_id: int, gid: str) -> None:
  await asyncio.sleep(int(DEFAULTS.vote_delay_sec) + 1)
  state = load_state()
  game = get_game(state, lobby_chat_id)
  if not _is_running(game) or str(game.get("server_game_id")) != gid:
    return
  vote = game.get("end_vote") or {}
  if not vote.get("active"):
    return
  yes_count = len(set(vote.get("yes") or []))
  human_count = int(vote.get("human_count", 0))
  need = (human_count // 2) + 1
  vote["active"] = False
  game["end_vote"] = vote
  set_game(state, lobby_chat_id, game)
  save_state(state)
  if yes_count >= need:
    await bot.send_message(lobby_chat_id, "Большинство за завершение - завершаю игру.")
    await finish_game_now(bot, lobby_chat_id, gid)
    return
  await bot.send_message(lobby_chat_id, "Большинство не набрано - продолжаем игру.")


async def notify_pet_offer(bot: Bot, lobby_chat_id: int, offerer_uid: int, target_role: str) -> None:
  state = load_state()
  game = get_game(state, lobby_chat_id)
  if not _is_running(game):
    return
  gid = str(game.get("server_game_id"))
  offerer_role = (game.get("humans") or {}).get(str(offerer_uid))
  if not offerer_role:
    return
  target_uid_str = (game.get("role_to_uid") or {}).get(target_role)
  if not target_uid_str:
    await bot.send_message(lobby_chat_id, f"🐾 Не удалось найти игрока с ролью {target_role}.")
    return
  target_uid = int(target_uid_str)
  await _send_dm(bot, offerer_uid, f"🐾 Предложение обмена отправлено игроку {target_role}. Ждем ответа.")
  try:
    player_state = api.player_state(gid, target_uid)
  except Exception:
    player_state = {"ok": False, "reason": "Не удалось загрузить состояние"}
  text = (
    "🐾 Вам предлагают обмен питомцами!\n"
    f"От: {offerer_role}\n\n"
    "Ваш текущий статус:\n"
    f"{render_player_info(player_state)}"
  )
  sent = await _send_dm(bot, target_uid, text, reply_markup=kb_pet_offer_answer(lobby_chat_id, target_uid, offerer_role))
  players = game.get("players") or {}
  if sent:
    await bot.send_message(
      lobby_chat_id,
      f"🐾 {mention(players.get(str(target_uid), {'name': target_role}))}, вам пришло предложение обмена от "
      f"{mention(players.get(str(offerer_uid), {'name': offerer_role}))}. Ответьте в личке с ботом.",
    )
  else:
    await bot.send_message(lobby_chat_id, f"🐾 Игроку {target_role} предложили обмен от {offerer_role}, но личка недоступна.")


async def notify_pet_answer(bot: Bot, lobby_chat_id: int, target_uid: int, offerer_role: str, accepted: bool) -> None:
  state = load_state()
  game = get_game(state, lobby_chat_id)
  if not _is_running(game):
    return
  offerer_uid_str = (game.get("role_to_uid") or {}).get(offerer_role)
  if not offerer_uid_str:
    return
  offerer_uid = int(offerer_uid_str)
  target_role = (game.get("humans") or {}).get(str(target_uid), "")
  text = (
    f"🐾 Игрок {target_role} принял обмен. Обмен произойдет при завершении дня."
    if accepted
    else f"🐾 Игрок {target_role} отказался от обмена."
  )
  await _send_dm(bot, offerer_uid, text)


async def notify_house_offer(bot: Bot, lobby_chat_id: int, offerer_uid: int, target_role: str) -> None:
  state = load_state()
  game = get_game(state, lobby_chat_id)
  if not _is_running(game):
    return
  gid = str(game.get("server_game_id"))
  offerer_role = (game.get("humans") or {}).get(str(offerer_uid))
  if not offerer_role:
    return
  target_uid_str = (game.get("role_to_uid") or {}).get(target_role)
  if not target_uid_str:
    await bot.send_message(lobby_chat_id, f"🏠 Не удалось найти игрока с ролью {target_role}.")
    return
  target_uid = int(target_uid_str)
  await _send_dm(bot, offerer_uid, f"🏠 Предложение обмена домами отправлено игроку {target_role}. Ждем ответа.")
  try:
    player_state = api.player_state(gid, target_uid)
  except Exception:
    player_state = {"ok": False, "reason": "Не удалось загрузить состояние"}
  text = (
    "🏠 Вам предлагают обмен домами!\n"
    f"От: {offerer_role}\n\n"
    "Ваш текущий статус:\n"
    f"{render_player_info(player_state)}"
  )
  sent = await _send_dm(bot, target_uid, text, reply_markup=kb_house_offer_answer(lobby_chat_id, target_uid, offerer_role))
  players = game.get("players") or {}
  if sent:
    await bot.send_message(
      lobby_chat_id,
      f"🏠 {mention(players.get(str(target_uid), {'name': target_role}))}, вам пришло предложение обмена домами от "
      f"{mention(players.get(str(offerer_uid), {'name': offerer_role}))}. Ответьте в личке с ботом.",
    )
  else:
    await bot.send_message(lobby_chat_id, f"🏠 Игроку {target_role} предложили обмен домами от {offerer_role}, но личка недоступна.")


async def notify_house_answer(bot: Bot, lobby_chat_id: int, target_uid: int, offerer_role: str, accepted: bool) -> None:
  state = load_state()
  game = get_game(state, lobby_chat_id)
  if not _is_running(game):
    return
  offerer_uid_str = (game.get("role_to_uid") or {}).get(offerer_role)
  if not offerer_uid_str:
    return
  offerer_uid = int(offerer_uid_str)
  target_role = (game.get("humans") or {}).get(str(target_uid), "")
  text = (
    f"🏠 Игрок {target_role} принял обмен домами. Обмен произойдет при завершении дня."
    if accepted
    else f"🏠 Игрок {target_role} отказался от обмена домами."
  )
  await _send_dm(bot, offerer_uid, text)
