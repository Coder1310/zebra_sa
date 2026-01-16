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
  turn_delay_sec: int = 30
  vote_delay_sec: int = 30


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


def _mention(user: dict[str, Any]) -> str:
  u = user.get("username")
  if u:
    return f"@{u}"
  return user.get("name", "user")


def _kb_lobby(game_id: str) -> Any:
  kb = InlineKeyboardBuilder()
  kb.button(text="✅ Join", callback_data=f"lobby:{game_id}:join")
  kb.button(text="❌ Leave", callback_data=f"lobby:{game_id}:leave")
  kb.button(text="🚀 Start now (host)", callback_data=f"lobby:{game_id}:start")
  kb.button(text="🛑 Cancel (host)", callback_data=f"lobby:{game_id}:cancel")
  kb.adjust(2, 2)
  return kb.as_markup()


def _kb_finish_vote(gid: str) -> Any:
  kb = InlineKeyboardBuilder()
  kb.button(text="✅ Завершить", callback_data=f"vote:{gid}:yes")
  kb.button(text="❌ Продолжать", callback_data=f"vote:{gid}:no")
  kb.adjust(2)
  return kb.as_markup()


def _kb_actions_for_player(gid: str, user_id: int, ps: dict[str, Any]) -> Any:
  kb = InlineKeyboardBuilder()

  graph = str(ps.get("graph", "ring"))
  loc = int(ps.get("location", 1))
  left = int(ps.get("left_house", 1))
  right = int(ps.get("right_house", 1))

  offers_in = ps.get("pet_offers_in") or []
  co_humans = ps.get("co_located_humans") or []

  # базовые
  kb.button(text="⏸ Stay", callback_data=f"act:{gid}:{user_id}:stay")
  if graph != "full":
    kb.button(text=f"⬅ Left (to {left})", callback_data=f"act:{gid}:{user_id}:left")
    kb.button(text=f"➡ Right (to {right})", callback_data=f"act:{gid}:{user_id}:right")
  else:
    kb.button(text="🏃 Choose destination", callback_data=f"goto:{gid}:{user_id}:0")

  # обмен питомцами - только если рядом есть живые игроки
  if len(co_humans) > 0:
    kb.button(text="🐾 Propose pet swap", callback_data=f"petmenu:{gid}:{user_id}")

  # входящие предложения - accept/decline
  for offerer in offers_in[:4]:
    kb.button(text=f"✅ Accept swap from {offerer}", callback_data=f"act:{gid}:{user_id}:pet_accept:{offerer}")
    kb.button(text=f"❌ Decline {offerer}", callback_data=f"act:{gid}:{user_id}:pet_decline:{offerer}")

  kb.button(text="🛑 End game", callback_data=f"end:{gid}:{user_id}")
  kb.adjust(2, 2, 2)
  return kb.as_markup()


def _kb_pet_targets(gid: str, user_id: int, targets: list[str]) -> Any:
  kb = InlineKeyboardBuilder()
  for t in targets[:8]:
    kb.button(text=f"Swap with {t}", callback_data=f"act:{gid}:{user_id}:pet_offer:{t}")
  kb.button(text="Cancel", callback_data=f"petmenu_cancel:{gid}:{user_id}")
  kb.adjust(2, 2, 2, 1)
  return kb.as_markup()


def _kb_goto_page(gid: str, user_id: int, houses: int, page: int, current: int) -> Any:
  per_page = 10
  start = page * per_page + 1
  end = min(houses, start + per_page - 1)

  kb = InlineKeyboardBuilder()
  for h in range(start, end + 1):
    if h == current:
      continue
    kb.button(text=f"Go {h}", callback_data=f"act:{gid}:{user_id}:go_to:{h}")

  if page > 0:
    kb.button(text="⬅ Prev", callback_data=f"goto:{gid}:{user_id}:{page-1}")
  if end < houses:
    kb.button(text="Next ➡", callback_data=f"goto:{gid}:{user_id}:{page+1}")

  kb.button(text="Close", callback_data=f"goto_close:{gid}:{user_id}")
  kb.adjust(5, 2, 1)
  return kb.as_markup()


def _format_lobby(game: dict[str, Any]) -> str:
  players = game.get("players", {})
  need = int(game["settings"]["players"])
  cur = len(players)
  left = max(0, int(game["deadline_at"] - time.time()))
  invites = game.get("invited_usernames") or []

  lines: list[str] = []
  lines.append("🎮 ZEBRA: лобби")
  lines.append(f"Игроки: {cur}/{need}")
  for p in players.values():
    lines.append(f"- {_mention(p)}")
  if invites:
    lines.append("")
    lines.append("Приглашены: " + " ".join(f"@{x}" for x in invites))
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


def _api_player_state(gid: str, user_id: int) -> dict[str, Any]:
  r = requests.get(f"{_api_base()}/game/{gid}/player_state", params={"user_id": user_id}, timeout=60)
  r.raise_for_status()
  return r.json()


def _api_action(gid: str, user_id: int, kind: str, dst: Optional[int] = None, target: Optional[str] = None) -> dict[str, Any]:
  payload = {"user_id": user_id, "kind": kind, "dst": dst, "target": target}
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


def _render_player_info(ps: dict[str, Any]) -> str:
  if not ps.get("ok"):
    return f"Ошибка: {ps.get('reason')}"

  role = ps["role"]
  day = ps["day"]
  days_total = ps["days_total"]
  home = ps["home"]
  loc = ps["location"]
  m1 = float(ps.get("m1", 0.0))

  trip = ps.get("trip") or {}
  in_trip = bool(trip.get("active"))

  co_all = ps.get("co_located_all") or []
  co_h = ps.get("co_located_humans") or []
  offers = ps.get("pet_offers_in") or []

  lines: list[str] = []
  lines.append(f"🗓 День {day}/{days_total}")
  lines.append(f"Вы: {role}. Ваш дом: {home}. Сейчас: дом {loc}.")
  lines.append(f"Ваши атрибуты: pet={ps.get('pet')} drink={ps.get('drink')} smoke={ps.get('smoke')}")
  if in_trip:
    lines.append(f"Вы в пути: {trip.get('src')} -> {trip.get('dst')} (осталось {trip.get('remaining')} дн.)")
  if co_all:
    lines.append("В вашем доме сейчас: " + ", ".join(co_all))
  if offers:
    lines.append("Входящие предложения обмена питомцами: " + ", ".join(offers))
  lines.append(f"M1 сейчас: {m1:.3f}")

  # таблица знаний (может быть длинной - ограничим)
  know = ps.get("knowledge") or []
  total = len(know) * 5
  known_cnt = 0
  rows: list[str] = []
  for r in know:
    hid = r["house"]
    parts = []
    for cat in ("color", "nationality", "pet", "drink", "smoke"):
      v = r.get(cat)
      if v is not None:
        known_cnt += 1
      parts.append(f"{cat}={v if v is not None else '?'}")
    rows.append(f"{hid}: " + " ".join(parts))

  # чтобы не упереться в лимит Telegram
  table_text = "\n".join(rows)
  if len(table_text) > 2500:
    lines.append(f"Знания: {known_cnt}/{total} заполнено. (таблица слишком большая, показ сокращен)")
    # покажем только дома где известно >2 полей
    shortlist = []
    for r in know:
      cnt = sum(1 for cat in ("color", "nationality", "pet", "drink", "smoke") if r.get(cat) is not None)
      if cnt >= 3:
        hid = r["house"]
        parts = []
        for cat in ("color", "nationality", "pet", "drink", "smoke"):
          v = r.get(cat)
          parts.append(f"{cat}={v if v is not None else '?'}")
        shortlist.append((cnt, f"{hid}: " + " ".join(parts)))
    shortlist.sort(reverse=True, key=lambda x: x[0])
    for _, line in shortlist[:10]:
      lines.append(line)
  else:
    lines.append("")
    lines.append("Ваши знания по домам:")
    lines.append(table_text)

  if co_h:
    lines.append("")
    lines.append("Живые игроки рядом: " + ", ".join(co_h))

  return "\n".join(lines)


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

  humans = game.get("humans", {})
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
  await m.answer("Команды: /game [@user ...], /help, /end")


@router.message(Command("help"))
async def cmd_help(m: Message) -> None:
  await m.answer(
    "/game @user1 @user2 ... - создать лобби и пригласить людей по тегам\n"
    "/end - предложить завершить игру (если людей 1 - завершит сразу)\n"
    "Каждый день каждому игроку приходит персональное сообщение с кнопками.\n"
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

  invited_usernames: list[str] = []
  parts = (m.text or "").split()
  for t in parts[1:]:
    if t.startswith("@") and len(t) > 1:
      invited_usernames.append(t[1:].lower())

  lobby_id = str(int(time.time()))
  settings = asdict(DEFAULTS)

  host_user = {
    "name": (m.from_user.full_name or "host"),
    "username": (m.from_user.username or None),
  }

  game = {
    "id": lobby_id,
    "chat_id": chat_id,
    "host_id": m.from_user.id,
    "created_at": time.time(),
    "deadline_at": time.time() + int(settings["lobby_delay_sec"]),
    "stage": "lobby",
    "settings": settings,
    "invited_usernames": invited_usernames,
    "players": {
      str(m.from_user.id): host_user
    },
  }

  _set_game(state, chat_id, game)
  _save_state(state)

  await m.answer(_format_lobby(game), reply_markup=_kb_lobby(lobby_id))
  if invited_usernames:
    await m.answer("Приглашение отправлено: " + " ".join(f"@{x}" for x in invited_usernames))

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

    invited = game.get("invited_usernames") or []
    u_name = (q.from_user.username or "").lower()
    is_invited = (not invited) or (u_name in invited) or (uid == host_id)

    if action == "join":
      if game.get("stage") != "lobby":
        await q.answer("Лобби закрыто")
        return
      if not is_invited:
        await q.answer("Ты не в списке приглашенных (нужен @username)")
        return

      players = game.setdefault("players", {})
      need = int(game["settings"]["players"])
      if str(uid) not in players:
        if len(players) >= need:
          await q.answer("Нет мест")
          return
        players[str(uid)] = {
          "name": (q.from_user.full_name or "user"),
          "username": (q.from_user.username or None),
        }

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
      if uid == host_id:
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
    # end:{gid}:{uid}
    parts = data.split(":")
    if len(parts) != 3:
      await q.answer()
      return
    gid = parts[1]
    uid = int(parts[2])

    if q.from_user.id != uid:
      await q.answer("Это не твоя кнопка")
      return

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

  if data.startswith("goto:"):
    # goto:{gid}:{uid}:{page}
    parts = data.split(":")
    if len(parts) != 4:
      await q.answer()
      return
    gid = parts[1]
    uid = int(parts[2])
    page = int(parts[3])

    if q.from_user.id != uid:
      await q.answer("Это не твоя кнопка")
      return

    if not game or game.get("stage") != "running" or game.get("server_game_id") != gid:
      await q.answer("Игра не активна")
      return

    ps = _api_player_state(gid, uid)
    houses = int(game["settings"]["houses"])
    cur = int(ps.get("location", 1))
    try:
      await BOT.send_message(chat_id, f"Выбор дома (страница {page})", reply_markup=_kb_goto_page(gid, uid, houses, page, cur))
    except Exception:
      pass
    await q.answer("Ок")
    return

  if data.startswith("goto_close:"):
    parts = data.split(":")
    if len(parts) != 3:
      await q.answer()
      return
    uid = int(parts[2])
    if q.from_user.id != uid:
      await q.answer("Это не твоя кнопка")
      return
    await q.answer("Ок")
    return

  if data.startswith("petmenu:"):
    # petmenu:{gid}:{uid}
    parts = data.split(":")
    if len(parts) != 3:
      await q.answer()
      return
    gid = parts[1]
    uid = int(parts[2])

    if q.from_user.id != uid:
      await q.answer("Это не твоя кнопка")
      return

    ps = _api_player_state(gid, uid)
    targets = ps.get("co_located_humans") or []
    if not targets:
      await q.answer("Нет живых игроков рядом")
      return

    await BOT.send_message(chat_id, "С кем обменяться питомцами? (нужно согласие второго игрока)", reply_markup=_kb_pet_targets(gid, uid, targets))
    await q.answer("Ок")
    return

  if data.startswith("petmenu_cancel:"):
    parts = data.split(":")
    if len(parts) != 3:
      await q.answer()
      return
    uid = int(parts[2])
    if q.from_user.id != uid:
      await q.answer("Это не твоя кнопка")
      return
    await q.answer("Ок")
    return

  if data.startswith("act:"):
    # act:{gid}:{uid}:{kind} либо act:{gid}:{uid}:{kind}:{arg}
    parts = data.split(":")
    if len(parts) not in (4, 5):
      await q.answer()
      return
    gid = parts[1]
    uid = int(parts[2])
    kind = parts[3]
    arg = parts[4] if len(parts) == 5 else None

    if q.from_user.id != uid:
      await q.answer("Это не твоя кнопка")
      return

    if not game or game.get("stage") != "running" or game.get("server_game_id") != gid:
      await q.answer("Игра не активна")
      return

    humans = game.get("humans", {})
    if str(uid) not in humans:
      await q.answer("Ты не игрок")
      return

    try:
      if kind == "go_to":
        dst = int(arg) if arg else None
        _api_action(gid, uid, "go_to", dst=dst)
      elif kind in ("stay", "left", "right"):
        _api_action(gid, uid, kind)
      elif kind == "pet_offer":
        _api_action(gid, uid, "pet_offer", target=arg)
      elif kind == "pet_accept":
        _api_action(gid, uid, "pet_accept", target=arg)
      elif kind == "pet_decline":
        _api_action(gid, uid, "pet_decline", target=arg)
      else:
        await q.answer("Неизвестное действие")
        return

      await q.answer("Ход принят")

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

  lines = ["🎮 Игра началась (пошагово). Роли людей:"]
  for uid, role in humans_map.items():
    lines.append(f"- {_mention(game['players'][uid])} -> {role}")
  await BOT.send_message(chat_id, "\n".join(lines))

  await _send_turn_prompts(chat_id, gid, game)
  asyncio.create_task(_turn_timer(chat_id, gid))


async def _send_turn_prompts(chat_id: int, gid: str, game: dict[str, Any]) -> None:
  humans = game.get("humans", {})
  for uid_str, role in humans.items():
    uid = int(uid_str)
    ps = _api_player_state(gid, uid)
    text = f"{_mention(game['players'][uid_str])}\n\n{_render_player_info(ps)}"
    await BOT.send_message(chat_id, text, reply_markup=_kb_actions_for_player(gid, uid, ps))


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

  reports = res.get("reports") or {}
  if res.get("day_finished") is not None:
    await BOT.send_message(chat_id, f"✅ День {res['day_finished']} завершен. События дня:")

  # отправим "повествование" живым игрокам
  state = _load_state()
  game = _get_game(state, chat_id)
  if game and game.get("stage") == "running":
    humans = game.get("humans", {})
    for uid_str, role in humans.items():
      p = game["players"].get(uid_str, {"name": "user"})
      mention = _mention(p)
      lines = reports.get(role, [])
      if lines:
        await BOT.send_message(chat_id, mention + "\n" + "\n".join(lines))

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

  if game:
    await _send_turn_prompts(chat_id, gid, game)


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
