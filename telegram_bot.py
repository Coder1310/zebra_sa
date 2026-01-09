#!/usr/bin/env python3
from __future__ import annotations

import asyncio
import os
import time
import zipfile
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Optional

import requests
import yaml
from aiogram import Bot, Dispatcher, Router
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery, FSInputFile
from aiogram.utils.keyboard import InlineKeyboardBuilder


ROOT_DIR = Path(__file__).resolve().parent
DATA_DIR = ROOT_DIR / "data"
LOGS_DIR = DATA_DIR / "logs"
BOT_STATE_PATH = LOGS_DIR / "bot_state.yaml"

ROLES_6 = ["Russian", "Englishman", "Chinese", "German", "French", "American"]

router = Router()
BOT: Bot


@dataclass
class Defaults:
  players: int = 6
  houses: int = 6
  days: int = 50
  share: str = "meet"
  noise: float = 0.2
  graph: str = "ring"        # ring | full
  lobby_delay_sec: int = 60
  turn_delay_sec: int = 30   # время на ход каждого дня
  vote_delay_sec: int = 30   # время на голосование завершения


DEFAULTS = Defaults()


def _load_dotenv(path: Path) -> None:
  if not path.exists():
    return
  for raw in path.read_text(encoding="utf-8").splitlines():
    line = raw.strip()
    if (not line) or line.startswith("#") or "=" not in line:
      continue
    k, v = line.split("=", 1)
    k = k.strip()
    v = v.strip().strip('"').strip("'")
    if k and k not in os.environ:
      os.environ[k] = v


def _api_base() -> str:
  return os.getenv("ZEBRA_API", "http://127.0.0.1:8000")


def _load_state() -> dict[str, Any]:
  if not BOT_STATE_PATH.exists():
    return {}
  try:
    return yaml.safe_load(BOT_STATE_PATH.read_text(encoding="utf-8")) or {}
  except Exception:
    return {}


def _save_state(state: dict[str, Any]) -> None:
  BOT_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
  BOT_STATE_PATH.write_text(
    yaml.safe_dump(state, allow_unicode=True, sort_keys=False),
    encoding="utf-8",
  )


def _get_game(state: dict[str, Any], chat_id: int) -> Optional[dict[str, Any]]:
  return (state.get("games") or {}).get(str(chat_id))


def _set_game(state: dict[str, Any], chat_id: int, game: Optional[dict[str, Any]]) -> None:
  state.setdefault("games", {})
  if game is None:
    state["games"].pop(str(chat_id), None)
  else:
    state["games"][str(chat_id)] = game


def _kb_lobby(game_id: str) -> Any:
  kb = InlineKeyboardBuilder()
  kb.button(text="✅ Join", callback_data=f"lobby:{game_id}:join")
  kb.button(text="❌ Leave", callback_data=f"lobby:{game_id}:leave")
  kb.button(text="🚀 Start now (host)", callback_data=f"lobby:{game_id}:start")
  kb.button(text="🛑 Cancel (host)", callback_data=f"lobby:{game_id}:cancel")
  kb.adjust(2, 2)
  return kb.as_markup()


def _kb_actions(gid: str, graph: str) -> Any:
  kb = InlineKeyboardBuilder()
  kb.button(text="⏸ Stay", callback_data=f"act:{gid}:stay")
  kb.button(text="⬅ Left", callback_data=f"act:{gid}:left")
  kb.button(text="➡ Right", callback_data=f"act:{gid}:right")
  kb.button(text="🏠 Exchange house", callback_data=f"act:{gid}:house_exchange")
  kb.button(text="🐾 Exchange pet", callback_data=f"act:{gid}:pet_exchange")
  kb.button(text="🛑 End game", callback_data=f"end:{gid}")

  if graph == "full":
    for i in range(1, 7):
      kb.button(text=f"Go {i}", callback_data=f"act:{gid}:go_to:{i}")
    kb.adjust(3, 2, 1, 6)
  else:
    kb.adjust(3, 2, 1)

  return kb.as_markup()


def _kb_finish_vote(gid: str) -> Any:
  kb = InlineKeyboardBuilder()
  kb.button(text="✅ Завершить", callback_data=f"vote:{gid}:yes")
  kb.button(text="❌ Продолжать", callback_data=f"vote:{gid}:no")
  kb.adjust(2)
  return kb.as_markup()


def _format_lobby(game: dict[str, Any]) -> str:
  players = game.get("players", {})
  need = int(game["settings"]["players"])
  cur = len(players)
  left = max(0, int(game["deadline_at"] - time.time()))

  lines: list[str] = []
  lines.append("🎮 ZEBRA: лобби")
  lines.append(f"Игроки: {cur}/{need}")
  for p in players.values():
    lines.append(f"- {p.get('name', 'user')}")
  lines.append(f"Старт через: {left} сек")
  lines.append("")
  lines.append("Нажми Join. Кто не успеет - будет заменен ботом.")
  return "\n".join(lines)


def _api_create_game(cfg: dict[str, Any]) -> str:
  r = requests.post(f"{_api_base()}/game/create", json=cfg, timeout=60)
  r.raise_for_status()
  return r.json()["game_id"]


def _api_state(gid: str) -> dict[str, Any]:
  r = requests.get(f"{_api_base()}/game/{gid}/state", timeout=60)
  r.raise_for_status()
  return r.json()


def _api_action(gid: str, user_id: int, kind: str, dst: Optional[int] = None) -> dict[str, Any]:
  payload = {"user_id": user_id, "kind": kind, "dst": dst}
  r = requests.post(f"{_api_base()}/game/{gid}/action", json=payload, timeout=60)
  r.raise_for_status()
  return r.json()


def _api_step(gid: str) -> dict[str, Any]:
  r = requests.post(f"{_api_base()}/game/{gid}/step", timeout=60 * 10)
  r.raise_for_status()
  return r.json()


def _api_finish(gid: str) -> dict[str, Any]:
  r = requests.post(f"{_api_base()}/game/{gid}/finish", timeout=60 * 10)
  r.raise_for_status()
  return r.json()


def _zip_files(zip_path: Path, paths: list[Path]) -> None:
  zip_path.parent.mkdir(parents=True, exist_ok=True)
  with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
    for p in paths:
      if p.exists():
        zf.write(p, arcname=p.name)


async def _request_finish(chat_id: int, requester_id: int) -> None:
  state = _load_state()
  game = _get_game(state, chat_id)
  if not game or game.get("stage") != "running":
    await BOT.send_message(chat_id, "Игра не активна.")
    return

  gid = game.get("server_game_id")
  if not gid:
    await BOT.send_message(chat_id, "Игра еще не создана на сервере.")
    return

  humans = game.get("humans", {})  # uid -> role
  human_count = len(humans)

  if human_count <= 1:
    await BOT.send_message(chat_id, "Живой игрок один - завершаю игру.")
    await _finish_game_now(chat_id, gid)
    return

  vote = game.get("end_vote")
  if vote and vote.get("active"):
    await BOT.send_message(chat_id, "Голосование уже идет.")
    return

  game["end_vote"] = {
    "active": True,
    "yes": [],
    "no": [],
    "deadline_at": time.time() + int(DEFAULTS.vote_delay_sec),
    "human_count": human_count,
  }
  _set_game(state, chat_id, game)
  _save_state(state)

  need = (human_count // 2) + 1
  await BOT.send_message(
    chat_id,
    f"Голосование за завершение игры. Нужно минимум {need} голосов 'Завершить'.",
    reply_markup=_kb_finish_vote(gid),
  )
  asyncio.create_task(_vote_timer(chat_id, gid))


async def _vote_timer(chat_id: int, gid: str) -> None:
  await asyncio.sleep(int(DEFAULTS.vote_delay_sec) + 1)

  state = _load_state()
  game = _get_game(state, chat_id)
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
  _set_game(state, chat_id, game)
  _save_state(state)

  if yes_cnt >= need:
    await BOT.send_message(chat_id, "Большинство за завершение - завершаю игру.")
    await _finish_game_now(chat_id, gid)
  else:
    await BOT.send_message(chat_id, "Большинство не набрано - продолжаем игру.")


async def _finish_game_now(chat_id: int, gid: str) -> None:
  try:
    res = _api_finish(gid)

    lb = res.get("leaderboard") or []
    day_finished = res.get("day_finished")
    if day_finished is not None:
      lines = [f"🏁 Игра завершена на дне {day_finished}. Топ M1:"]
    else:
      lines = ["🏁 Игра завершена. Топ M1:"]

    for i, item in enumerate(lb[:6], start=1):
      lines.append(f"{i}) {item[0]}: {float(item[1]):.3f}")
    await BOT.send_message(chat_id, "\n".join(lines))

    files = res.get("files") or {}
    if files:
      metrics = Path(files["metrics"])
      events = Path(files["csv"])
      xml = Path(files["xml"])
      zip_path = LOGS_DIR / f"game_{gid}.zip"
      _zip_files(zip_path, [metrics, events, xml])
      await BOT.send_document(chat_id, FSInputFile(str(zip_path)))
  finally:
    state = _load_state()
    _set_game(state, chat_id, None)
    _save_state(state)


@router.message(Command("start"))
async def cmd_start(m: Message) -> None:
  await m.answer("Команды: /game, /help, /end")


@router.message(Command("help"))
async def cmd_help(m: Message) -> None:
  await m.answer(
    "/game - создать лобби и играть пошагово\n"
    "/end - предложить завершить игру (если людей 1 - завершит сразу)\n"
    "Каждый день выбирай действие кнопками. Если молчишь - автоход.\n"
  )


@router.message(Command("end"))
async def cmd_end(m: Message) -> None:
  await _request_finish(m.chat.id, m.from_user.id)


@router.message(Command("game"))
async def cmd_game(m: Message) -> None:
  state = _load_state()
  chat_id = m.chat.id
  if _get_game(state, chat_id) is not None:
    await m.answer("В этом чате уже есть активная игра. Отмени кнопкой Cancel.")
    return

  lobby_id = str(int(time.time()))
  settings = asdict(DEFAULTS)

  game = {
    "id": lobby_id,
    "chat_id": chat_id,
    "host_id": m.from_user.id,
    "created_at": time.time(),
    "deadline_at": time.time() + int(settings["lobby_delay_sec"]),
    "stage": "lobby",
    "settings": settings,
    "players": {
      str(m.from_user.id): {"name": (m.from_user.username or m.from_user.full_name or "host")}
    },
  }

  _set_game(state, chat_id, game)
  _save_state(state)

  await m.answer(_format_lobby(game), reply_markup=_kb_lobby(lobby_id))
  asyncio.create_task(_auto_start_lobby(chat_id, lobby_id, int(settings["lobby_delay_sec"]) + 1))


async def _auto_start_lobby(chat_id: int, lobby_id: str, delay_sec: int) -> None:
  await asyncio.sleep(delay_sec)
  state = _load_state()
  game = _get_game(state, chat_id)
  if not game or game.get("id") != lobby_id or game.get("stage") != "lobby":
    return
  await _start_game(chat_id, lobby_id)


@router.callback_query()
async def on_cb(q: CallbackQuery) -> None:
  data = q.data or ""
  state = _load_state()
  chat_id = q.message.chat.id if q.message else q.from_user.id
  game = _get_game(state, chat_id)

  if data.startswith("lobby:"):
    parts = data.split(":")
    if len(parts) != 3:
      await q.answer()
      return
    _, lobby_id, action = parts

    if not game or game.get("id") != lobby_id:
      await q.answer("Игра не найдена")
      return

    host_id = int(game["host_id"])
    uid = q.from_user.id

    if action == "join":
      if game.get("stage") != "lobby":
        await q.answer("Лобби закрыто")
        return
      players = game.setdefault("players", {})
      need = int(game["settings"]["players"])
      if str(uid) not in players:
        if len(players) >= need:
          await q.answer("Нет мест")
          return
        players[str(uid)] = {"name": (q.from_user.username or q.from_user.full_name or "user")}
      _set_game(state, chat_id, game)
      _save_state(state)
      try:
        await q.message.edit_text(_format_lobby(game), reply_markup=_kb_lobby(lobby_id))
      except Exception:
        pass
      await q.answer("Ок")
      return

    if action == "leave":
      if game.get("stage") != "lobby":
        await q.answer("Лобби закрыто")
        return
      if str(uid) == str(host_id):
        await q.answer("Хост не может выйти. Cancel.")
        return
      game.get("players", {}).pop(str(uid), None)
      _set_game(state, chat_id, game)
      _save_state(state)
      try:
        await q.message.edit_text(_format_lobby(game), reply_markup=_kb_lobby(lobby_id))
      except Exception:
        pass
      await q.answer("Ок")
      return

    if action == "start":
      if uid != host_id:
        await q.answer("Только хост")
        return
      await q.answer("Старт")
      await _start_game(chat_id, lobby_id)
      return

    if action == "cancel":
      if uid != host_id:
        await q.answer("Только хост")
        return
      _set_game(state, chat_id, None)
      _save_state(state)
      try:
        await q.message.edit_text("Игра отменена.")
      except Exception:
        pass
      await q.answer("Ок")
      return

  if data.startswith("end:"):
    parts = data.split(":")
    if len(parts) != 2:
      await q.answer()
      return
    gid = parts[1]

    if not game or game.get("stage") != "running" or game.get("server_game_id") != gid:
      await q.answer("Игра не активна")
      return

    await q.answer("Ок")
    await _request_finish(chat_id, q.from_user.id)
    return

  if data.startswith("vote:"):
    parts = data.split(":")
    if len(parts) != 3:
      await q.answer()
      return
    gid = parts[1]
    choice = parts[2]

    if not game or game.get("stage") != "running" or game.get("server_game_id") != gid:
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

    uid = q.from_user.id
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
    _set_game(state, chat_id, game)
    _save_state(state)

    if yes_cnt >= need:
      vote["active"] = False
      game["end_vote"] = vote
      _set_game(state, chat_id, game)
      _save_state(state)
      await q.answer("Большинство набрано")
      await _finish_game_now(chat_id, gid)
      return

    await q.answer(f"Голос учтен: YES={yes_cnt}/{need}")
    return

  if data.startswith("act:"):
    parts = data.split(":")
    if len(parts) not in (3, 4):
      await q.answer()
      return
    gid = parts[1]
    kind = parts[2]
    dst = int(parts[3]) if len(parts) == 4 else None

    if not game or game.get("stage") != "running" or game.get("server_game_id") != gid:
      await q.answer("Игра не активна")
      return

    humans = game.get("humans", {})
    if str(q.from_user.id) not in humans:
      await q.answer("Ты не игрок в этой партии")
      return

    try:
      _api_action(gid, q.from_user.id, kind, dst)
      await q.answer("Принято")

      st = _api_state(gid)
      if len(st.get("pending_user_ids", [])) == 0:
        await _do_step_and_next(chat_id, gid)
    except Exception as e:
      await q.answer("Ошибка")
      await BOT.send_message(chat_id, f"Ошибка action: {e}")
    return

  await q.answer()


async def _start_game(chat_id: int, lobby_id: str) -> None:
  state = _load_state()
  game = _get_game(state, chat_id)
  if not game or game.get("id") != lobby_id or game.get("stage") != "lobby":
    return

  players = list(game.get("players", {}).items())
  need = int(game["settings"]["players"])

  humans = players[:need]
  roles = ROLES_6[:need]

  humans_payload = []
  humans_map = {}
  for i, (uid, p) in enumerate(humans):
    role = roles[i]
    humans_payload.append({"user_id": int(uid), "name": p.get("name", "user"), "role": role})
    humans_map[uid] = role

  cfg = {
    "agents": need,
    "houses": int(game["settings"]["houses"]),
    "days": int(game["settings"]["days"]),
    "share": str(game["settings"]["share"]),
    "noise": float(game["settings"]["noise"]),
    "seed": None,
    "graph": str(game["settings"]["graph"]),
    "humans": humans_payload,
  }

  await BOT.send_message(chat_id, "🎮 Создаю игровую сессию на сервере...")
  gid = _api_create_game(cfg)

  game["stage"] = "running"
  game["server_game_id"] = gid
  game["humans"] = humans_map
  game["end_vote"] = None

  _set_game(state, chat_id, game)
  _save_state(state)

  lines = ["🎮 Игра началась (пошагово).", "Роли людей:"]
  for uid, role in humans_map.items():
    lines.append(f"- {game['players'][uid]['name']} -> {role}")
  lines.append("")
  lines.append("Каждый день выбери действие кнопками. Если молчишь - автоход.")
  await BOT.send_message(chat_id, "\n".join(lines))

  await _send_turn_prompt(chat_id, gid)
  asyncio.create_task(_turn_timer(chat_id, gid))


async def _send_turn_prompt(chat_id: int, gid: str) -> None:
  st = _api_state(gid)
  day = int(st["day"])
  days_total = int(st["days_total"])
  graph = str(st["graph"])
  pending = st.get("pending_user_ids", [])

  text = f"🗓 День {day}/{days_total}\nОжидаю ходы: {len(pending)}"
  await BOT.send_message(chat_id, text, reply_markup=_kb_actions(gid, graph))


async def _turn_timer(chat_id: int, gid: str) -> None:
  while True:
    await asyncio.sleep(int(DEFAULTS.turn_delay_sec))

    state = _load_state()
    game = _get_game(state, chat_id)
    if not game or game.get("stage") != "running" or game.get("server_game_id") != gid:
      return

    st = _api_state(gid)
    if int(st["day"]) > int(st["days_total"]):
      return

    pending = st.get("pending_user_ids", [])
    if len(pending) > 0:
      await _do_step_and_next(chat_id, gid)


async def _do_step_and_next(chat_id: int, gid: str) -> None:
  res = _api_step(gid)

  if res.get("day_finished") is not None:
    lb = res.get("leaderboard") or []
    lines = [f"✅ День {res['day_finished']} завершен. Топ M1:"]
    for i, item in enumerate(lb[:6], start=1):
      lines.append(f"{i}) {item[0]}: {float(item[1]):.3f}")
    await BOT.send_message(chat_id, "\n".join(lines))

  if res.get("done"):
    files = res.get("files") or {}
    if files:
      metrics = Path(files["metrics"])
      events = Path(files["csv"])
      xml = Path(files["xml"])
      zip_path = LOGS_DIR / f"game_{gid}.zip"
      _zip_files(zip_path, [metrics, events, xml])
      await BOT.send_message(chat_id, "🏁 Игра окончена. Отправляю логи.")
      await BOT.send_document(chat_id, FSInputFile(str(zip_path)))

    state = _load_state()
    _set_game(state, chat_id, None)
    _save_state(state)
    return

  await _send_turn_prompt(chat_id, gid)


def _env(name: str) -> str:
  v = os.getenv(name)
  if not v:
    raise RuntimeError(f"env {name} is required")
  return v


async def main() -> None:
  _load_dotenv(ROOT_DIR / ".env")

  token = _env("BOT_TOKEN")
  bot = Bot(token=token)
  global BOT
  BOT = bot

  dp = Dispatcher()
  dp.include_router(router)
  await dp.start_polling(bot)


if __name__ == "__main__":
  asyncio.run(main())
