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

API_BASE = os.getenv("ZEBRA_API", "http://127.0.0.1:8000")


@dataclass
class Defaults:
  players: int = 6
  houses: int = 6
  days: int = 50
  share: str = "meet"
  noise: float = 0.2
  graph: str = "ring"        # ring | full
  time_delay_sec: int = 60
  strategy_delay_sec: int = 60
  slow_sleep_ms: int = 0     # 0 = fast


DEFAULTS = Defaults()
ROLES_6 = ["Russian", "Englishman", "Chinese", "German", "French", "American"]

router = Router()
BOT: Bot


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


def _preset_strategy(role: str, preset: str) -> dict[str, Any]:
  base = {
    "Russian": {"p_to": [0, 20, 0, 20, 20, 40], "p_house_exch": 10, "p_pet_exch": 10},
    "Englishman": {"p_to": [0, 0, 30, 30, 10, 30], "p_house_exch": 10, "p_pet_exch": 0},
    "Chinese": {"p_to": [0, 0, 0, 30, 60, 10], "p_house_exch": 0, "p_pet_exch": 20},
    "German": {"p_to": [0, 0, 0, 80, 10, 10], "p_house_exch": 10, "p_pet_exch": 10},
    "French": {"p_to": [10, 20, 0, 0, 0, 70], "p_house_exch": 10, "p_pet_exch": 20},
    "American": {"p_to": [10, 30, 0, 10, 10, 40], "p_house_exch": 10, "p_pet_exch": 10},
  }.get(role, {"p_to": [17, 17, 16, 17, 17, 16], "p_house_exch": 0, "p_pet_exch": 0})

  if preset == "default":
    return dict(base)

  if preset == "explorer":
    s = dict(base)
    s["p_house_exch"] = max(0, int(s["p_house_exch"]) - 5)
    s["p_pet_exch"] = max(0, int(s["p_pet_exch"]) - 5)
    p = list(s["p_to"])
    if len(p) == 6:
      p[5] += 10
      p[0] += 5
      p[1] += 5
      p[2] = max(0, p[2] - 10)
      p[3] = max(0, p[3] - 5)
      p[4] = max(0, p[4] - 5)
    s["p_to"] = p
    return s

  if preset == "trader":
    s = dict(base)
    s["p_house_exch"] = min(100, int(s["p_house_exch"]) + 15)
    s["p_pet_exch"] = min(100, int(s["p_pet_exch"]) + 15)
    return s

  return dict(base)


def _kb_lobby(game_id: str) -> Any:
  kb = InlineKeyboardBuilder()
  kb.button(text="✅ Join", callback_data=f"game:{game_id}:join")
  kb.button(text="❌ Leave", callback_data=f"game:{game_id}:leave")
  kb.button(text="🚀 Start now (host)", callback_data=f"game:{game_id}:start")
  kb.button(text="🛑 Cancel (host)", callback_data=f"game:{game_id}:cancel")
  kb.adjust(2, 2)
  return kb.as_markup()


def _kb_presets(game_id: str) -> Any:
  kb = InlineKeyboardBuilder()
  kb.button(text="Default", callback_data=f"game:{game_id}:preset:default")
  kb.button(text="Explorer", callback_data=f"game:{game_id}:preset:explorer")
  kb.button(text="Trader", callback_data=f"game:{game_id}:preset:trader")
  kb.adjust(3)
  return kb.as_markup()


def _format_lobby(game: dict[str, Any]) -> str:
  players = game.get("players", {})
  need = int(game["settings"]["players"])
  cur = len(players)

  dl = float(game.get("deadline_at", 0))
  left = max(0, int(dl - time.time()))

  lines = []
  lines.append("🎮 ZEBRA: лобби")
  lines.append(f"Игроки: {cur}/{need}")
  for p in players.values():
    lines.append(f"- {p.get('name', 'user')}")
  lines.append(f"Старт через: {left} сек")
  lines.append("")
  lines.append("Нажми Join. Кто не успеет - будет заменен ботом.")
  return "\n".join(lines)


def _api_create_session(cfg: dict[str, Any]) -> str:
  r = requests.post(f"{API_BASE}/session/create", json=cfg, timeout=60)
  r.raise_for_status()
  return r.json()["session_id"]


def _api_run_session(session_id: str) -> dict[str, Any]:
  r = requests.post(f"{API_BASE}/session/{session_id}/run", timeout=60 * 30)
  r.raise_for_status()
  return r.json()


def _zip_files(zip_path: Path, paths: list[Path]) -> None:
  zip_path.parent.mkdir(parents=True, exist_ok=True)
  with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
    for p in paths:
      if p.exists():
        zf.write(p, arcname=p.name)


@router.message(Command("start"))
async def cmd_start(m: Message) -> None:
  await m.answer("Команды: /game, /help")


@router.message(Command("help"))
async def cmd_help(m: Message) -> None:
  await m.answer(
    "🎮 /game - создать лобби и сыграть\n"
    "Служебное:\n"
    "/run - запуск дефолтной симуляции (без лобби)\n"
  )


@router.message(Command("game"))
async def cmd_game(m: Message) -> None:
  state = _load_state()
  chat_id = m.chat.id

  if _get_game(state, chat_id) is not None:
    await m.answer("В этом чате уже есть активная игра. Отмени кнопкой Cancel.")
    return

  game_id = str(int(time.time()))
  settings = asdict(DEFAULTS)

  game = {
    "id": game_id,
    "chat_id": chat_id,
    "host_id": m.from_user.id,
    "created_at": time.time(),
    "deadline_at": time.time() + int(settings["time_delay_sec"]),
    "stage": "lobby",
    "settings": settings,
    "players": {
      str(m.from_user.id): {
        "name": (m.from_user.username or m.from_user.full_name or "host"),
        "preset": "default",
      }
    },
  }

  _set_game(state, chat_id, game)
  _save_state(state)

  msg = await m.answer(_format_lobby(game), reply_markup=_kb_lobby(game_id))
  game["lobby_msg_id"] = msg.message_id
  _set_game(state, chat_id, game)
  _save_state(state)

  delay = int(settings["time_delay_sec"]) + 1
  asyncio.create_task(_auto_start_lobby(chat_id, game_id, delay))


async def _auto_start_lobby(chat_id: int, game_id: str, delay_sec: int) -> None:
  await asyncio.sleep(delay_sec)

  state = _load_state()
  game = _get_game(state, chat_id)
  if not game or game.get("id") != game_id:
    return
  if game.get("stage") != "lobby":
    return

  await _start_game(chat_id, game_id)


@router.callback_query()
async def on_cb(q: CallbackQuery) -> None:
  data = q.data or ""
  if not data.startswith("game:"):
    await q.answer()
    return

  parts = data.split(":")
  if len(parts) < 3:
    await q.answer()
    return

  game_id = parts[1]
  action = parts[2]

  state = _load_state()
  chat_id = q.message.chat.id if q.message else q.from_user.id
  game = _get_game(state, chat_id)
  if not game or game.get("id") != game_id:
    await q.answer("Игра не найдена")
    return

  host_id = int(game["host_id"])
  uid = q.from_user.id

  if action == "join":
    if game.get("stage") != "lobby":
      await q.answer("Лобби уже закрыто")
      return
    players = game.setdefault("players", {})
    if str(uid) not in players:
      need = int(game["settings"]["players"])
      if len(players) >= need:
        await q.answer("Нет мест")
        return
      players[str(uid)] = {
        "name": (q.from_user.username or q.from_user.full_name or "user"),
        "preset": "default",
      }
    _set_game(state, chat_id, game)
    _save_state(state)
    await _refresh_lobby(q, game)
    await q.answer("Ок")
    return

  if action == "leave":
    if game.get("stage") != "lobby":
      await q.answer("Лобби уже закрыто")
      return
    if str(uid) == str(host_id):
      await q.answer("Хост не может выйти. Нажми Cancel.")
      return
    game.get("players", {}).pop(str(uid), None)
    _set_game(state, chat_id, game)
    _save_state(state)
    await _refresh_lobby(q, game)
    await q.answer("Ок")
    return

  if action == "start":
    if uid != host_id:
      await q.answer("Только хост")
      return
    await q.answer("Запускаю")
    await _start_game(chat_id, game_id)
    return

  if action == "cancel":
    if uid != host_id:
      await q.answer("Только хост")
      return
    _set_game(state, chat_id, None)
    _save_state(state)
    try:
      if q.message:
        await q.message.edit_text("Игра отменена.")
    except Exception:
      pass
    await q.answer("Ок")
    return

  if action == "preset":
    if game.get("stage") != "strategy":
      await q.answer("Сейчас нельзя")
      return
    if len(parts) != 4:
      await q.answer()
      return
    preset = parts[3]
    game["players"].setdefault(str(uid), {"name": "user"})["preset"] = preset
    _set_game(state, chat_id, game)
    _save_state(state)
    await q.answer(f"Preset: {preset}")
    return

  await q.answer()


async def _refresh_lobby(q: CallbackQuery, game: dict[str, Any]) -> None:
  try:
    if q.message:
      await q.message.edit_text(_format_lobby(game), reply_markup=_kb_lobby(game["id"]))
  except Exception:
    pass


async def _start_game(chat_id: int, game_id: str) -> None:
  state = _load_state()
  game = _get_game(state, chat_id)
  if not game or game.get("id") != game_id:
    return
  if game.get("stage") != "lobby":
    return

  game["stage"] = "strategy"
  game["strategy_deadline_at"] = time.time() + int(game["settings"]["strategy_delay_sec"])
  _set_game(state, chat_id, game)
  _save_state(state)

  players = list(game["players"].items())
  need = int(game["settings"]["players"])

  humans = players[:need]
  roles = ROLES_6[:need]

  for i, (uid, p) in enumerate(humans):
    p["role"] = roles[i]

  bots_cnt = need - len(humans)
  for j in range(bots_cnt):
    game["players"][f"bot{j}"] = {
      "name": f"bot{j}",
      "role": roles[len(humans) + j],
      "preset": "default",
      "bot": True,
    }

  _set_game(state, chat_id, game)
  _save_state(state)

  lines = ["🎮 Игра начинается!", "Роли:"]
  for p in game["players"].values():
    lines.append(f"- {p['name']} -> {p['role']}")
  lines.append("")
  lines.append("Выбери стиль (кнопки) в течение TimeDelay. Кто не выберет - Default.")

  await BOT.send_message(chat_id, "\n".join(lines), reply_markup=_kb_presets(game_id))

  delay = int(game["settings"]["strategy_delay_sec"]) + 1
  asyncio.create_task(_auto_run_after_strategy(chat_id, game_id, delay))


async def _auto_run_after_strategy(chat_id: int, game_id: str, delay_sec: int) -> None:
  await asyncio.sleep(delay_sec)

  state = _load_state()
  game = _get_game(state, chat_id)
  if not game or game.get("id") != game_id:
    return
  if game.get("stage") != "strategy":
    return

  game["stage"] = "running"
  _set_game(state, chat_id, game)
  _save_state(state)

  strategies: dict[str, dict[str, Any]] = {}
  for p in game["players"].values():
    role = p.get("role")
    if not role:
      continue
    preset = p.get("preset", "default")
    strategies[role] = _preset_strategy(role, preset)

  cfg = {
    "agents": int(game["settings"]["players"]),
    "houses": int(game["settings"]["houses"]),
    "days": int(game["settings"]["days"]),
    "share": str(game["settings"]["share"]),
    "noise": float(game["settings"]["noise"]),
    "graph": str(game["settings"]["graph"]),
    "use_zebra_defaults": True,
    "strategies": strategies,
    "sleep_ms_per_day": int(game["settings"]["slow_sleep_ms"]),
  }

  await BOT.send_message(chat_id, "⏳ Запускаю симуляцию...")

  try:
    sid = _api_create_session(cfg)
    res = _api_run_session(sid)

    metrics = Path(res["metrics"])
    events = Path(res["csv"])
    xml = Path(res["xml"])

    header = metrics.read_text(encoding="utf-8").splitlines()[0].split(",")[1:]
    last_line = metrics.read_text(encoding="utf-8").strip().splitlines()[-1]
    vals = [float(x) for x in last_line.split(",")[1:]]
    rating = sorted(zip(header, vals), key=lambda x: x[1], reverse=True)

    text = ["🏁 Результаты (M1 в последний день):"]
    for i, (n, v) in enumerate(rating, start=1):
      text.append(f"{i}) {n}: {v:.3f}")
    text.append("")
    text.append("Логи отправляю архивом.")
    await BOT.send_message(chat_id, "\n".join(text))

    zip_path = LOGS_DIR / f"game_{sid}.zip"
    _zip_files(zip_path, [metrics, events, xml])
    await BOT.send_document(chat_id, FSInputFile(str(zip_path)))


  except Exception as e:
    await BOT.send_message(chat_id, f"Ошибка запуска: {e}")

  state = _load_state()
  _set_game(state, chat_id, None)
  _save_state(state)


@router.message(Command("run"))
async def cmd_run(m: Message) -> None:
  cfg = {
    "agents": 6,
    "houses": 6,
    "days": 50,
    "share": "meet",
    "noise": 0.2,
    "graph": "ring",
    "use_zebra_defaults": True,
  }
  await m.answer("⏳ Запускаю дефолтную симуляцию...")
  try:
    sid = _api_create_session(cfg)
    res = _api_run_session(sid)
    metrics = Path(res["metrics"])
    events = Path(res["csv"])
    xml = Path(res["xml"])
    zip_path = LOGS_DIR / f"run_{sid}.zip"
    _zip_files(zip_path, [metrics, events, xml])
    await m.answer_document(FSInputFile(str(zip_path)))
  except Exception as e:
    await m.answer(f"Ошибка: {e}")


def _env(name: str) -> str:
  v = os.getenv(name)
  if not v:
    raise RuntimeError(f"env {name} is required")
  return v


async def main() -> None:
  token = _env("BOT_TOKEN")
  bot = Bot(token=token)

  global BOT
  BOT = bot

  dp = Dispatcher()
  dp.include_router(router)
  await dp.start_polling(bot)


if __name__ == "__main__":
  asyncio.run(main())
