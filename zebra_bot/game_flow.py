from __future__ import annotations

import asyncio
import time
import zipfile
from pathlib import Path
from typing import Any, Optional

from aiogram import Bot
from aiogram.types import FSInputFile

from zebra_bot import api
from zebra_bot.config import DEFAULTS, LOGS_DIR, defaults_dict
from zebra_bot.keyboards import (
  kb_actions_for_player,
  kb_finish_vote,
  kb_goto_page,
  kb_lobby,
  kb_pet_offer_answer,
  kb_pet_targets,
)
from zebra_bot.render import agent_names, format_lobby, render_player_info
from zebra_bot.storage import (
  get_game,
  set_game,
  load_state,
  save_state,
  mention,
  user_id_by_username,
)


def _zip_files(zip_path: Path, paths: list[Path]) -> None:
  zip_path.parent.mkdir(parents=True, exist_ok=True)
  with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
    for p in paths:
      if p.exists():
        zf.write(p, arcname=p.name)


async def _send_dm(bot: Bot, uid: int, text: str, reply_markup: Any | None = None) -> bool:
  try:
    await bot.send_message(uid, text, reply_markup=reply_markup)
    return True
  except Exception:
    return False


async def sync_lobby_message(bot: Bot, lobby_chat_id: int, force_text: str | None = None) -> None:
  state = load_state()
  game = get_game(state, lobby_chat_id)
  if not game:
    return
  msg_id = game.get("lobby_message_id")
  if not msg_id:
    return
  text = force_text or format_lobby(game)
  try:
    await bot.edit_message_text(
      text,
      chat_id=lobby_chat_id,
      message_id=int(msg_id),
      reply_markup=kb_lobby(lobby_chat_id, game["id"]),
    )
  except Exception:
    try:
      msg = await bot.send_message(lobby_chat_id, text, reply_markup=kb_lobby(lobby_chat_id, game["id"]))
      game["lobby_message_id"] = msg.message_id
      set_game(state, lobby_chat_id, game)
      save_state(state)
    except Exception:
      pass


async def create_lobby(bot: Bot, lobby_chat_id: int, host_user: Any, invited_usernames: list[str]) -> None:
  state = load_state()

  if get_game(state, lobby_chat_id) is not None:
    await bot.send_message(lobby_chat_id, "В этом чате уже есть активная игра. Отмени кнопкой Cancel.")
    return

  lobby_id = str(int(time.time()))
  settings = defaults_dict()

  host_payload = {
    "name": host_user.full_name or "host",
    "username": (host_user.username or "").lower() or None,
  }

  game = {
    "id": lobby_id,
    "chat_id": lobby_chat_id,
    "host_id": int(host_user.id),
    "created_at": time.time(),
    "deadline_at": time.time() + int(settings["lobby_delay_sec"]),
    "stage": "lobby",
    "settings": settings,
    "invited_usernames": invited_usernames,
    "players": {
      str(host_user.id): host_payload,
    },
  }

  set_game(state, lobby_chat_id, game)
  save_state(state)

  msg = await bot.send_message(lobby_chat_id, format_lobby(game), reply_markup=kb_lobby(lobby_chat_id, lobby_id))
  state = load_state()
  game = get_game(state, lobby_chat_id) or game
  game["lobby_message_id"] = msg.message_id
  set_game(state, lobby_chat_id, game)
  save_state(state)

  if invited_usernames:
    not_known: list[str] = []
    for u in invited_usernames:
      uid = user_id_by_username(state, u)
      if uid is None:
        not_known.append(u)
        continue
      await _send_dm(
        bot,
        uid,
        f"🎮 Тебя пригласили в игру ZEBRA.\nЛобби в чате {lobby_chat_id}.\nНажми Join.",
        reply_markup=kb_lobby(lobby_chat_id, lobby_id),
      )
    if not_known:
      await bot.send_message(
        lobby_chat_id,
        "Не смог отправить приглашение (они не нажимали /start боту): " + " ".join(f"@{x}" for x in not_known),
      )

  asyncio.create_task(_auto_start_lobby(bot, lobby_chat_id, lobby_id, int(settings["lobby_delay_sec"]) + 1))


async def _auto_start_lobby(bot: Bot, lobby_chat_id: int, lobby_id: str, delay_sec: int) -> None:
  await asyncio.sleep(delay_sec)
  state = load_state()
  game = get_game(state, lobby_chat_id)
  if not game or game.get("id") != lobby_id or game.get("stage") != "lobby":
    return
  await start_game(bot, lobby_chat_id)


async def start_game(bot: Bot, lobby_chat_id: int) -> None:
  state = load_state()
  game = get_game(state, lobby_chat_id)
  if not game or game.get("stage") != "lobby":
    return

  players = list((game.get("players") or {}).items())
  need = int(game["settings"]["players"])
  houses = int(game["settings"]["houses"])
  roles = agent_names(need, houses)

  humans = players[:need]
  humans_payload: list[dict[str, Any]] = []
  humans_map: dict[str, str] = {}
  role_to_uid: dict[str, str] = {}

  for i, (uid_str, p) in enumerate(humans):
    role = roles[i]
    humans_payload.append({"user_id": int(uid_str), "name": p.get("name", "user"), "role": role})
    humans_map[str(uid_str)] = role
    role_to_uid[role] = str(uid_str)

  cfg = {
    "agents": need,
    "houses": houses,
    "days": int(game["settings"]["days"]),
    "share": str(game["settings"]["share"]),
    "noise": float(game["settings"]["noise"]),
    "seed": None,
    "graph": str(game["settings"]["graph"]),
    "humans": humans_payload,
  }

  await bot.send_message(lobby_chat_id, "🎮 Создаю игровую сессию на сервере...")
  gid = api.create_game(cfg)

  game["stage"] = "running"
  game["server_game_id"] = gid
  game["humans"] = humans_map
  game["role_to_uid"] = role_to_uid
  game["end_vote"] = None

  set_game(state, lobby_chat_id, game)
  save_state(state)

  lines = ["🎮 Игра началась. Роли людей:"]
  for uid_str, role in humans_map.items():
    lines.append(f"- {mention(game['players'][uid_str])} -> {role}")
  lines.append("")
  lines.append("Ходы и приватные сообщения приходят в личку.")
  await bot.send_message(lobby_chat_id, "\n".join(lines))

  for uid_str in humans_map.keys():
    uid = int(uid_str)
    ok = await send_private_turn_state(bot, lobby_chat_id, uid)
    if not ok:
      p = game["players"].get(uid_str, {"name": "user"})
      await bot.send_message(lobby_chat_id, f"⚠ Не смог написать в личку {mention(p)}. Пусть он откроет бота и нажмет /start.")

  await send_group_waiting(bot, lobby_chat_id)
  asyncio.create_task(turn_timer(bot, lobby_chat_id))


async def send_private_turn_state(bot: Bot, lobby_chat_id: int, uid: int) -> bool:
  state = load_state()
  game = get_game(state, lobby_chat_id)
  if not game or game.get("stage") != "running":
    return False
  gid = str(game.get("server_game_id"))
  ps = api.player_state(gid, uid)
  text = render_player_info(ps)
  return await _send_dm(bot, uid, text, reply_markup=kb_actions_for_player(lobby_chat_id, uid, ps))


async def send_group_waiting(bot: Bot, lobby_chat_id: int) -> None:
  state = load_state()
  game = get_game(state, lobby_chat_id)
  if not game or game.get("stage") != "running":
    return
  gid = str(game.get("server_game_id"))
  st = api.state(gid)
  pending = st.get("pending_user_ids", [])
  if not pending:
    await bot.send_message(lobby_chat_id, "⏳ Сейчас никто не должен ходить (все в пути/все походили).")
    return
  names: list[str] = []
  for uid in pending:
    p = game.get("players", {}).get(str(uid))
    names.append(mention(p) if p else str(uid))
  await bot.send_message(lobby_chat_id, "⏳ Ожидаю ходы от: " + ", ".join(names))


async def turn_timer(bot: Bot, lobby_chat_id: int) -> None:
  while True:
    await asyncio.sleep(int(DEFAULTS.turn_delay_sec))

    state = load_state()
    game = get_game(state, lobby_chat_id)
    if not game or game.get("stage") != "running":
      return

    gid = str(game.get("server_game_id"))
    st = api.state(gid)
    pending = st.get("pending_user_ids", [])

    any_trip = False
    for uid_str in (game.get("humans") or {}).keys():
      uid = int(uid_str)
      ps = api.player_state(gid, uid)
      trip = (ps.get("trip") or {})
      if ps.get("ok") and bool(trip.get("active")):
        any_trip = True
        break

    if pending or any_trip:
      await do_step_and_next(bot, lobby_chat_id)


async def maybe_step_and_next(bot: Bot, lobby_chat_id: int) -> None:
  state = load_state()
  game = get_game(state, lobby_chat_id)
  if not game or game.get("stage") != "running":
    return
  gid = str(game.get("server_game_id"))
  st = api.state(gid)
  if len(st.get("pending_user_ids", [])) == 0:
    await do_step_and_next(bot, lobby_chat_id)
  else:
    await send_group_waiting(bot, lobby_chat_id)


async def do_step_and_next(bot: Bot, lobby_chat_id: int) -> None:
  state = load_state()
  game = get_game(state, lobby_chat_id)
  if not game or game.get("stage") != "running":
    return
  gid = str(game.get("server_game_id"))

  res = api.step(gid)
  day_finished = res.get("day_finished")
  if day_finished is not None:
    await bot.send_message(lobby_chat_id, f"✅ День {day_finished} завершен.")

  reports = res.get("reports") or {}
  for uid_str, role in (game.get("humans") or {}).items():
    uid = int(uid_str)
    lines = reports.get(role, [])
    if lines:
      await _send_dm(bot, uid, "\n".join(lines))

  if res.get("done"):
    await finish_game_now(bot, lobby_chat_id, gid)
    return

  for uid_str in (game.get("humans") or {}).keys():
    uid = int(uid_str)
    await send_private_turn_state(bot, lobby_chat_id, uid)

  await send_group_waiting(bot, lobby_chat_id)


async def finish_game_now(bot: Bot, lobby_chat_id: int, gid: str) -> None:
  try:
    res = api.finish(gid)

    lb = res.get("leaderboard") or []
    day_finished = res.get("day_finished")
    if day_finished is not None:
      lines = [f"🏁 Игра завершена на дне {day_finished}. Топ M1:"]
    else:
      lines = ["🏁 Игра завершена. Топ M1:"]

    for i, item in enumerate(lb[:10], start=1):
      lines.append(f"{i}) {item[0]}: {float(item[1]):.3f}")
    await bot.send_message(lobby_chat_id, "\n".join(lines))

    files = res.get("files") or {}
    if files:
      metrics = Path(files["metrics"])
      events = Path(files["csv"])
      xml = Path(files["xml"])
      zip_path = LOGS_DIR / f"game_{gid}.zip"
      _zip_files(zip_path, [metrics, events, xml])
      await bot.send_document(lobby_chat_id, FSInputFile(str(zip_path)))
  finally:
    state = load_state()
    set_game(state, lobby_chat_id, None)
    save_state(state)


async def request_finish(bot: Bot, lobby_chat_id: int, requester_id: int) -> None:
  state = load_state()
  game = get_game(state, lobby_chat_id)
  if not game or game.get("stage") != "running":
    await bot.send_message(lobby_chat_id, "Игра не активна.")
    return

  gid = game.get("server_game_id")
  if not gid:
    await bot.send_message(lobby_chat_id, "Игра еще не создана.")
    return

  humans = game.get("humans", {})
  human_count = len(humans)

  if human_count <= 1:
    await bot.send_message(lobby_chat_id, "Живой игрок один - завершаю игру.")
    await finish_game_now(bot, lobby_chat_id, gid)
    return

  vote = game.get("end_vote")
  if vote and vote.get("active"):
    await bot.send_message(lobby_chat_id, "Голосование уже идет.")
    return

  game["end_vote"] = {
    "active": True,
    "yes": [],
    "no": [],
    "deadline_at": time.time() + int(DEFAULTS.vote_delay_sec),
    "human_count": human_count,
  }
  set_game(state, lobby_chat_id, game)
  save_state(state)

  need = (human_count // 2) + 1
  await bot.send_message(
    lobby_chat_id,
    f"Голосование за завершение игры. Нужно минимум {need} голосов 'Завершить'.",
    reply_markup=kb_finish_vote(lobby_chat_id),
  )
  asyncio.create_task(_vote_timer(bot, lobby_chat_id, gid))


async def _vote_timer(bot: Bot, lobby_chat_id: int, gid: str) -> None:
  await asyncio.sleep(int(DEFAULTS.vote_delay_sec) + 1)

  state = load_state()
  game = get_game(state, lobby_chat_id)
  if not game or game.get("stage") != "running" or game.get("server_game_id") != gid:
    return

  vote = game.get("end_vote") or {}
  if not vote.get("active"):
    return

  yes_cnt = len(set(vote.get("yes", [])))
  human_count = int(vote.get("human_count", 0))
  need = (human_count // 2) + 1

  vote["active"] = False
  game["end_vote"] = vote
  set_game(state, lobby_chat_id, game)
  save_state(state)

  if yes_cnt >= need:
    await bot.send_message(lobby_chat_id, "Большинство за завершение - завершаю игру.")
    await finish_game_now(bot, lobby_chat_id, gid)
  else:
    await bot.send_message(lobby_chat_id, "Большинство не набрано - продолжаем игру.")


async def notify_pet_offer(bot: Bot, lobby_chat_id: int, offerer_uid: int, target_role: str) -> None:
  state = load_state()
  game = get_game(state, lobby_chat_id)
  if not game or game.get("stage") != "running":
    return
  gid = str(game.get("server_game_id"))

  offerer_role = (game.get("humans") or {}).get(str(offerer_uid))
  if not offerer_role:
    return

  target_uid_str = (game.get("role_to_uid") or {}).get(target_role)
  if not target_uid_str:
    return
  target_uid = int(target_uid_str)

  await _send_dm(bot, offerer_uid, f"🐾 Предложение обмена отправлено игроку {target_role}. Ждем ответа.")

  ps = api.player_state(gid, target_uid)
  text = (
    "🐾 Вам предлагают обмен питомцами!\n"
    f"От: {offerer_role}\n\n"
    "Ваш текущий статус:\n"
    f"{render_player_info(ps)}"
  )
  sent = await _send_dm(bot, target_uid, text, reply_markup=kb_pet_offer_answer(lobby_chat_id, target_uid, offerer_role))
  if not sent:
    await bot.send_message(lobby_chat_id, f"🐾 Игроку {target_role} предложили обмен от {offerer_role}, но личка недоступна.")


async def notify_pet_answer(bot: Bot, lobby_chat_id: int, target_uid: int, offerer_role: str, accepted: bool) -> None:
  state = load_state()
  game = get_game(state, lobby_chat_id)
  if not game or game.get("stage") != "running":
    return

  offerer_uid_str = (game.get("role_to_uid") or {}).get(offerer_role)
  if not offerer_uid_str:
    return
  offerer_uid = int(offerer_uid_str)

  target_role = (game.get("humans") or {}).get(str(target_uid), "")
  if accepted:
    await _send_dm(bot, offerer_uid, f"🐾 Игрок {target_role} принял обмен. Обмен произойдет при завершении дня.")
  else:
    await _send_dm(bot, offerer_uid, f"🐾 Игрок {target_role} отказался от обмена.")
