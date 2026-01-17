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
STATE_PATH = LOGS_DIR / "bot_state.yaml"

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
  graph: str = "ring"
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


def _env(name: str) -> str:
  v = os.getenv(name)
  if not v:
    raise RuntimeError(f"env {name} is required")
  return v


def _api_base() -> str:
  return os.getenv("ZEBRA_API", "http://127.0.0.1:8000")


def _load_state() -> dict[str, Any]:
  if not STATE_PATH.exists():
    return {}
  try:
    return yaml.safe_load(STATE_PATH.read_text(encoding="utf-8")) or {}
  except Exception:
    return {}


def _save_state(state: dict[str, Any]) -> None:
  STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
  STATE_PATH.write_text(
    yaml.safe_dump(state, allow_unicode=True, sort_keys=False),
    encoding="utf-8",
  )


def _ensure(state: dict[str, Any]) -> None:
  state.setdefault("users", {})          # username_lower -> {user_id, name, last_seen}
  state.setdefault("lobbies", {})        # lobby_id -> lobby dict
  state.setdefault("user_to_lobby", {})  # user_id(str) -> lobby_id


def _register_user(state: dict[str, Any], user: Any) -> None:
  _ensure(state)
  username = (getattr(user, "username", None) or "").strip()
  if not username:
    return
  key = username.lower()
  state["users"][key] = {
    "user_id": int(user.id),
    "name": getattr(user, "full_name", None) or getattr(user, "first_name", None) or "user",
    "last_seen": int(time.time()),
  }


def _mention(user: dict[str, Any]) -> str:
  u = user.get("username")
  if u:
    return f"@{u}"
  return user.get("name", "user")


def _zip_files(zip_path: Path, paths: list[Path]) -> None:
  zip_path.parent.mkdir(parents=True, exist_ok=True)
  with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
    for p in paths:
      if p.exists():
        zf.write(p, arcname=p.name)


def _format_lobby(lobby: dict[str, Any]) -> str:
  players = lobby.get("players", {})
  need = int(lobby["settings"]["players"])
  cur = len(players)
  left = max(0, int(lobby["deadline_at"] - time.time()))
  invites = lobby.get("invited_usernames") or []

  lines: list[str] = []
  lines.append("🎮 ZEBRA: лобби")
  lines.append(f"Код комнаты: {lobby['id']}")
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


def _kb_lobby(lobby_id: str) -> Any:
  kb = InlineKeyboardBuilder()
  kb.button(text="✅ Join", callback_data=f"lobby:{lobby_id}:join")
  kb.button(text="❌ Leave", callback_data=f"lobby:{lobby_id}:leave")
  kb.button(text="🚀 Start now (host)", callback_data=f"lobby:{lobby_id}:start")
  kb.button(text="🛑 Cancel (host)", callback_data=f"lobby:{lobby_id}:cancel")
  kb.adjust(2, 2)
  return kb.as_markup()


def _kb_invite(lobby_id: str) -> Any:
  kb = InlineKeyboardBuilder()
  kb.button(text="✅ Принять приглашение", callback_data=f"invite:{lobby_id}:accept")
  kb.button(text="❌ Отклонить", callback_data=f"invite:{lobby_id}:decline")
  kb.adjust(1, 1)
  return kb.as_markup()


def _kb_finish_vote(lobby_id: str) -> Any:
  kb = InlineKeyboardBuilder()
  kb.button(text="✅ Завершить", callback_data=f"vote:{lobby_id}:yes")
  kb.button(text="❌ Продолжать", callback_data=f"vote:{lobby_id}:no")
  kb.adjust(2)
  return kb.as_markup()


def _kb_actions_for_player(gid: str, lobby_id: str, user_id: int, ps: dict[str, Any]) -> Any:
  kb = InlineKeyboardBuilder()

  graph = str(ps.get("graph", "ring"))
  loc = int(ps.get("location", 1))
  left = int(ps.get("left_house", 1))
  right = int(ps.get("right_house", 1))

  offers_in = ps.get("pet_offers_in") or []
  co_humans = ps.get("co_located_humans") or []

  kb.button(text="⏸ Stay", callback_data=f"act:{lobby_id}:{gid}:{user_id}:stay")
  if graph != "full":
    kb.button(text=f"⬅ Left (to {left})", callback_data=f"act:{lobby_id}:{gid}:{user_id}:left")
    kb.button(text=f"➡ Right (to {right})", callback_data=f"act:{lobby_id}:{gid}:{user_id}:right")
  else:
    kb.button(text="🏃 Choose destination", callback_data=f"goto:{lobby_id}:{gid}:{user_id}:0")

  if len(co_humans) > 0:
    kb.button(text="🐾 Propose pet swap", callback_data=f"petmenu:{lobby_id}:{gid}:{user_id}")

  for offerer in offers_in[:4]:
    kb.button(text=f"✅ Accept swap from {offerer}", callback_data=f"act:{lobby_id}:{gid}:{user_id}:pet_accept:{offerer}")
    kb.button(text=f"❌ Decline {offerer}", callback_data=f"act:{lobby_id}:{gid}:{user_id}:pet_decline:{offerer}")

  kb.button(text="🛑 End game", callback_data=f"end:{lobby_id}:{gid}:{user_id}")
  kb.adjust(2, 2, 2)
  return kb.as_markup()


def _kb_pet_targets(lobby_id: str, gid: str, user_id: int, targets: list[str]) -> Any:
  kb = InlineKeyboardBuilder()
  for t in targets[:8]:
    kb.button(text=f"Swap with {t}", callback_data=f"act:{lobby_id}:{gid}:{user_id}:pet_offer:{t}")
  kb.button(text="Cancel", callback_data=f"petmenu_cancel:{lobby_id}:{gid}:{user_id}")
  kb.adjust(2, 2, 2, 1)
  return kb.as_markup()


def _kb_goto_page(lobby_id: str, gid: str, user_id: int, houses: int, page: int, current: int) -> Any:
  per_page = 10
  start = page * per_page + 1
  end = min(houses, start + per_page - 1)

  kb = InlineKeyboardBuilder()
  for h in range(start, end + 1):
    if h == current:
      continue
    kb.button(text=f"Go {h}", callback_data=f"act:{lobby_id}:{gid}:{user_id}:go_to:{h}")

  if page > 0:
    kb.button(text="⬅ Prev", callback_data=f"goto:{lobby_id}:{gid}:{user_id}:{page-1}")
  if end < houses:
    kb.button(text="Next ➡", callback_data=f"goto:{lobby_id}:{gid}:{user_id}:{page+1}")

  kb.button(text="Close", callback_data=f"goto_close:{lobby_id}:{gid}:{user_id}")
  kb.adjust(5, 2, 1)
  return kb.as_markup()


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
  return "\n".join(lines)


def _get_lobby(state: dict[str, Any], lobby_id: str) -> Optional[dict[str, Any]]:
  _ensure(state)
  return state["lobbies"].get(str(lobby_id))


def _set_lobby(state: dict[str, Any], lobby_id: str, lobby: Optional[dict[str, Any]]) -> None:
  _ensure(state)
  if lobby is None:
    state["lobbies"].pop(str(lobby_id), None)
  else:
    state["lobbies"][str(lobby_id)] = lobby


def _user_lobby_id(state: dict[str, Any], user_id: int) -> Optional[str]:
  _ensure(state)
  return state["user_to_lobby"].get(str(int(user_id)))


def _set_user_lobby(state: dict[str, Any], user_id: int, lobby_id: Optional[str]) -> None:
  _ensure(state)
  key = str(int(user_id))
  if lobby_id is None:
    state["user_to_lobby"].pop(key, None)
  else:
    state["user_to_lobby"][key] = str(lobby_id)


async def _try_edit_lobby_message(lobby: dict[str, Any]) -> None:
  chat_id = lobby.get("host_chat_id")
  msg_id = lobby.get("host_message_id")
  if not chat_id or not msg_id:
    return
  try:
    await BOT.edit_message_text(
      chat_id=int(chat_id),
      message_id=int(msg_id),
      text=_format_lobby(lobby),
      reply_markup=_kb_lobby(lobby["id"]),
    )
  except Exception:
    pass


async def _send_invites(state: dict[str, Any], lobby: dict[str, Any]) -> None:
  invited = lobby.get("invited_usernames") or []
  if not invited:
    return

  known = state.get("users", {})
  host = lobby.get("players", {}).get(str(lobby["host_id"]), {"name": "host"})
  host_text = _mention(host)

  failed: list[str] = []
  for uname in invited:
    key = uname.lower()
    rec = known.get(key)
    if rec is None:
      failed.append(f"@{uname}")
      continue
    uid = int(rec["user_id"])
    try:
      await BOT.send_message(
        uid,
        f"🎮 Вас пригласили в игру ZEBRA.\nХост: {host_text}\nКод комнаты: {lobby['id']}\n\nНажмите принять, чтобы присоединиться.",
        reply_markup=_kb_invite(lobby["id"]),
      )
    except Exception:
      failed.append(f"@{uname}")

  if failed:
    # хосту сообщаем, кого не смогли пригласить в личку
    try:
      await BOT.send_message(
        int(lobby["host_chat_id"]),
        "Не смог отправить приглашение в личку: " + " ".join(failed) + "\n"
        "Причины: пользователь не писал боту после обновления или запретил сообщения.\n"
        "Пусть они напишут боту /start один раз.",
      )
    except Exception:
      pass


async def _finish_game_now(lobby_id: str, gid: str) -> None:
  state = _load_state()
  lobby = _get_lobby(state, lobby_id)
  if not lobby:
    return

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

    humans = lobby.get("humans", {})
    for uid_str in humans.keys():
      try:
        await BOT.send_message(int(uid_str), "\n".join(lines))
      except Exception:
        pass

    files = res.get("files") or {}
    if files:
      metrics = Path(files["metrics"])
      events = Path(files["csv"])
      xml = Path(files["xml"])
      zip_path = LOGS_DIR / f"game_{gid}.zip"
      _zip_files(zip_path, [metrics, events, xml])

      for uid_str in humans.keys():
        try:
          await BOT.send_document(int(uid_str), FSInputFile(str(zip_path)))
        except Exception:
          pass
  finally:
    # чистим
    humans = lobby.get("humans", {})
    for uid_str in humans.keys():
      _set_user_lobby(state, int(uid_str), None)
    _set_lobby(state, lobby_id, None)
    _save_state(state)


async def _request_finish(lobby_id: str, requester_id: int) -> None:
  state = _load_state()
  lobby = _get_lobby(state, lobby_id)
  if not lobby or lobby.get("stage") != "running":
    return

  gid = lobby.get("server_game_id")
  if not gid:
    return

  humans = lobby.get("humans", {})
  human_count = len(humans)

  if human_count <= 1:
    await BOT.send_message(int(requester_id), "Живой игрок один - завершаю игру.")
    await _finish_game_now(lobby_id, gid)
    return

  vote = lobby.get("end_vote")
  if vote and vote.get("active"):
    await BOT.send_message(int(requester_id), "Голосование уже идет.")
    return

  lobby["end_vote"] = {
    "active": True,
    "yes": [],
    "no": [],
    "deadline_at": time.time() + int(DEFAULTS.vote_delay_sec),
    "human_count": human_count,
  }

  _set_lobby(state, lobby_id, lobby)
  _save_state(state)

  need = (human_count // 2) + 1
  for uid_str in humans.keys():
    try:
      await BOT.send_message(
        int(uid_str),
        f"Голосование за завершение игры. Нужно минимум {need} голосов 'Завершить'.",
        reply_markup=_kb_finish_vote(lobby_id),
      )
    except Exception:
      pass

  asyncio.create_task(_vote_timer(lobby_id))


async def _vote_timer(lobby_id: str) -> None:
  await asyncio.sleep(int(DEFAULTS.vote_delay_sec) + 1)

  state = _load_state()
  lobby = _get_lobby(state, lobby_id)
  if not lobby or lobby.get("stage") != "running":
    return

  vote = lobby.get("end_vote") or {}
  if not vote.get("active"):
    return

  yes_cnt = len(set(vote.get("yes", [])))
  human_count = int(vote.get("human_count", 0))
  need = (human_count // 2) + 1

  vote["active"] = False
  lobby["end_vote"] = vote
  _set_lobby(state, lobby_id, lobby)
  _save_state(state)

  if yes_cnt >= need:
    humans = lobby.get("humans", {})
    for uid_str in humans.keys():
      try:
        await BOT.send_message(int(uid_str), "Большинство за завершение - завершаю игру.")
      except Exception:
        pass
    await _finish_game_now(lobby_id, lobby["server_game_id"])
  else:
    humans = lobby.get("humans", {})
    for uid_str in humans.keys():
      try:
        await BOT.send_message(int(uid_str), "Большинство не набрано - продолжаем игру.")
      except Exception:
        pass


async def _send_turn_prompts(lobby_id: str) -> None:
  state = _load_state()
  lobby = _get_lobby(state, lobby_id)
  if not lobby or lobby.get("stage") != "running":
    return
  gid = lobby.get("server_game_id")
  if not gid:
    return

  humans = lobby.get("humans", {})
  for uid_str in humans.keys():
    uid = int(uid_str)
    ps = _api_player_state(gid, uid)
    txt = _render_player_info(ps)
    await BOT.send_message(uid, txt, reply_markup=_kb_actions_for_player(gid, lobby_id, uid, ps))


async def _do_step_and_next(lobby_id: str) -> None:
  state = _load_state()
  lobby = _get_lobby(state, lobby_id)
  if not lobby or lobby.get("stage") != "running":
    return
  gid = lobby.get("server_game_id")
  if not gid:
    return

  res = _api_step(gid)

  reports = res.get("reports") or {}
  humans = lobby.get("humans", {})

  if res.get("day_finished") is not None:
    for uid_str, role in humans.items():
      uid = int(uid_str)
      lines = reports.get(role, [])
      if lines:
        await BOT.send_message(uid, "✅ " + "\n".join(lines))

  if res.get("done"):
    await _finish_game_now(lobby_id, gid)
    return

  await _send_turn_prompts(lobby_id)


async def _turn_timer(lobby_id: str) -> None:
  while True:
    await asyncio.sleep(int(DEFAULTS.turn_delay_sec))

    state = _load_state()
    lobby = _get_lobby(state, lobby_id)
    if not lobby or lobby.get("stage") != "running":
      return

    gid = lobby.get("server_game_id")
    if not gid:
      return

    st = _api_state(gid)
    if int(st["day"]) > int(st["days_total"]):
      return

    pending = st.get("pending_user_ids", [])
    if len(pending) > 0:
      await _do_step_and_next(lobby_id)


async def _auto_start_lobby(lobby_id: str, delay_sec: int) -> None:
  await asyncio.sleep(delay_sec)
  state = _load_state()
  lobby = _get_lobby(state, lobby_id)
  if not lobby or lobby.get("stage") != "lobby":
    return
  await _start_game(lobby_id)


async def _start_game(lobby_id: str) -> None:
  state = _load_state()
  lobby = _get_lobby(state, lobby_id)
  if not lobby or lobby.get("stage") != "lobby":
    return

  players: dict[str, dict[str, Any]] = lobby.get("players", {})
  need = int(lobby["settings"]["players"])
  users_sorted = list(players.keys())[:need]

  humans_payload = []
  humans_map: dict[str, str] = {}

  for i, uid_str in enumerate(users_sorted):
    role = ROLES_6[i]
    p = players[uid_str]
    humans_payload.append({"user_id": int(uid_str), "name": p.get("name", "user"), "role": role})
    humans_map[uid_str] = role

  cfg = {
    "agents": need,
    "houses": int(lobby["settings"]["houses"]),
    "days": int(lobby["settings"]["days"]),
    "share": str(lobby["settings"]["share"]),
    "noise": float(lobby["settings"]["noise"]),
    "seed": None,
    "graph": str(lobby["settings"]["graph"]),
    "humans": humans_payload,
  }

  gid = _api_create_game(cfg)

  lobby["stage"] = "running"
  lobby["server_game_id"] = gid
  lobby["humans"] = humans_map
  lobby["end_vote"] = None

  _set_lobby(state, lobby_id, lobby)

  for uid_str in humans_map.keys():
    _set_user_lobby(state, int(uid_str), lobby_id)

  _save_state(state)

  # всем в личку
  lines = ["🎮 Игра началась. Роли людей:"]
  for uid_str, role in humans_map.items():
    lines.append(f"- {_mention(players[uid_str])} -> {role}")
  msg = "\n".join(lines)

  for uid_str in humans_map.keys():
    try:
      await BOT.send_message(int(uid_str), msg)
    except Exception:
      pass

  await _send_turn_prompts(lobby_id)
  asyncio.create_task(_turn_timer(lobby_id))


@router.message(Command("start"))
async def cmd_start(m: Message) -> None:
  state = _load_state()
  _register_user(state, m.from_user)
  _save_state(state)
  await m.answer("Ок. Теперь я могу приглашать тебя в игры в личку.\nКоманды: /game @user ... , /join CODE , /end")


@router.message(Command("join"))
async def cmd_join(m: Message) -> None:
  parts = (m.text or "").split()
  if len(parts) < 2:
    await m.answer("Формат: /join CODE")
    return
  code = parts[1].strip()

  state = _load_state()
  _register_user(state, m.from_user)

  lobby = _get_lobby(state, code)
  if not lobby or lobby.get("stage") != "lobby":
    await m.answer("Комната не найдена или уже запущена.")
    _save_state(state)
    return

  invited = lobby.get("invited_usernames") or []
  uname = (m.from_user.username or "").lower()
  is_invited = (not invited) or (uname in invited) or (int(m.from_user.id) == int(lobby["host_id"]))

  if not is_invited:
    await m.answer("Ты не в списке приглашенных.")
    _save_state(state)
    return

  players = lobby.setdefault("players", {})
  need = int(lobby["settings"]["players"])
  uid_str = str(m.from_user.id)
  if uid_str not in players:
    if len(players) >= need:
      await m.answer("Нет мест.")
      _save_state(state)
      return
    players[uid_str] = {"name": m.from_user.full_name or "user", "username": m.from_user.username or None}

  _set_lobby(state, code, lobby)
  _save_state(state)

  await m.answer("Вы присоединились к лобби. Ждите старта.")
  await _try_edit_lobby_message(lobby)


@router.message(Command("game"))
async def cmd_game(m: Message) -> None:
  state = _load_state()
  _register_user(state, m.from_user)
  _ensure(state)

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

  lobby = {
    "id": lobby_id,
    "host_id": int(m.from_user.id),
    "host_chat_id": int(m.chat.id),
    "host_message_id": None,
    "created_at": time.time(),
    "deadline_at": time.time() + int(settings["lobby_delay_sec"]),
    "stage": "lobby",
    "settings": settings,
    "invited_usernames": invited_usernames,
    "players": {
      str(m.from_user.id): host_user
    },
  }

  _set_lobby(state, lobby_id, lobby)
  _save_state(state)

  msg = await m.answer(_format_lobby(lobby), reply_markup=_kb_lobby(lobby_id))
  lobby["host_message_id"] = int(msg.message_id)
  _set_lobby(state, lobby_id, lobby)
  _save_state(state)

  if invited_usernames:
    await m.answer("Пытаюсь отправить приглашения в личку...")
    await _send_invites(state, lobby)

  asyncio.create_task(_auto_start_lobby(lobby_id, int(settings["lobby_delay_sec"]) + 1))


@router.message(Command("end"))
async def cmd_end(m: Message) -> None:
  state = _load_state()
  _register_user(state, m.from_user)
  lobby_id = _user_lobby_id(state, m.from_user.id)
  _save_state(state)
  if not lobby_id:
    await m.answer("Ты сейчас не в игре.")
    return
  await _request_finish(lobby_id, m.from_user.id)


@router.callback_query()
async def on_cb(q: CallbackQuery) -> None:
  data = q.data or ""

  state = _load_state()
  _register_user(state, q.from_user)
  _save_state(state)

  if data.startswith("invite:"):
    parts = data.split(":")
    if len(parts) != 3:
      await q.answer()
      return
    lobby_id = parts[1]
    act = parts[2]

    state = _load_state()
    lobby = _get_lobby(state, lobby_id)
    if not lobby or lobby.get("stage") != "lobby":
      await q.answer("Комната закрыта")
      return

    invited = lobby.get("invited_usernames") or []
    uname = (q.from_user.username or "").lower()
    is_invited = (not invited) or (uname in invited) or (int(q.from_user.id) == int(lobby["host_id"]))
    if not is_invited:
      await q.answer("Ты не приглашен")
      return

    if act == "decline":
      await q.answer("Ок")
      try:
        await BOT.send_message(int(lobby["host_chat_id"]), f"{q.from_user.username or q.from_user.full_name} отклонил приглашение.")
      except Exception:
        pass
      return

    # accept
    players = lobby.setdefault("players", {})
    need = int(lobby["settings"]["players"])
    uid_str = str(q.from_user.id)

    if uid_str not in players:
      if len(players) >= need:
        await q.answer("Нет мест")
        return
      players[uid_str] = {"name": q.from_user.full_name or "user", "username": q.from_user.username or None}

    _set_lobby(state, lobby_id, lobby)
    _save_state(state)

    await q.answer("Вы в лобби")
    await BOT.send_message(q.from_user.id, f"Вы присоединились к лобби. Код: {lobby_id}. Ждите старта.")
    await _try_edit_lobby_message(lobby)
    return

  if data.startswith("lobby:"):
    parts = data.split(":")
    if len(parts) != 3:
      await q.answer()
      return
    _, lobby_id, action = parts

    state = _load_state()
    lobby = _get_lobby(state, lobby_id)
    if not lobby:
      await q.answer("Комната не найдена")
      return

    host_id = int(lobby["host_id"])
    uid = int(q.from_user.id)

    invited = lobby.get("invited_usernames") or []
    u_name = (q.from_user.username or "").lower()
    is_invited = (not invited) or (u_name in invited) or (uid == host_id)

    if action == "join":
      if lobby.get("stage") != "lobby":
        await q.answer("Лобби закрыто")
        return
      if not is_invited:
        await q.answer("Ты не в списке приглашенных")
        return
      players = lobby.setdefault("players", {})
      need = int(lobby["settings"]["players"])
      if str(uid) not in players:
        if len(players) >= need:
          await q.answer("Нет мест")
          return
        players[str(uid)] = {"name": q.from_user.full_name or "user", "username": q.from_user.username or None}
      _set_lobby(state, lobby_id, lobby)
      _save_state(state)
      await _try_edit_lobby_message(lobby)
      await q.answer("Ок")
      return

    if action == "leave":
      if lobby.get("stage") != "lobby":
        await q.answer("Лобби закрыто")
        return
      if uid == host_id:
        await q.answer("Хост не может выйти. Cancel.")
        return
      lobby.get("players", {}).pop(str(uid), None)
      _set_lobby(state, lobby_id, lobby)
      _save_state(state)
      await _try_edit_lobby_message(lobby)
      await q.answer("Ок")
      return

    if action == "start":
      if uid != host_id:
        await q.answer("Только хост")
        return
      await q.answer("Старт")
      await _start_game(lobby_id)
      return

    if action == "cancel":
      if uid != host_id:
        await q.answer("Только хост")
        return
      # очистка
      players = lobby.get("players", {})
      for uid_str in players.keys():
        _set_user_lobby(state, int(uid_str), None)
      _set_lobby(state, lobby_id, None)
      _save_state(state)
      await q.answer("Ок")
      try:
        await BOT.edit_message_text(chat_id=int(lobby["host_chat_id"]), message_id=int(lobby["host_message_id"]), text="Игра отменена.")
      except Exception:
        pass
      return

  if data.startswith("end:"):
    # end:{lobby_id}:{gid}:{uid}
    parts = data.split(":")
    if len(parts) != 4:
      await q.answer()
      return
    lobby_id, gid, uid = parts[1], parts[2], int(parts[3])
    if int(q.from_user.id) != uid:
      await q.answer("Это не твоя кнопка")
      return
    await q.answer("Ок")
    await _request_finish(lobby_id, uid)
    return

  if data.startswith("vote:"):
    parts = data.split(":")
    if len(parts) != 3:
      await q.answer()
      return
    lobby_id = parts[1]
    choice = parts[2]

    state = _load_state()
    lobby = _get_lobby(state, lobby_id)
    if not lobby or lobby.get("stage") != "running":
      await q.answer("Игра не активна")
      return

    humans = lobby.get("humans", {})
    if str(q.from_user.id) not in humans:
      await q.answer("Ты не игрок")
      return

    vote = lobby.get("end_vote") or {}
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
    lobby["end_vote"] = vote

    _set_lobby(state, lobby_id, lobby)
    _save_state(state)

    human_count = int(vote.get("human_count", len(humans)))
    need = (human_count // 2) + 1
    yes_cnt = len(yes_list)

    if yes_cnt >= need:
      vote["active"] = False
      lobby["end_vote"] = vote
      _set_lobby(state, lobby_id, lobby)
      _save_state(state)
      await q.answer("Большинство набрано")
      await _finish_game_now(lobby_id, lobby["server_game_id"])
      return

    await q.answer(f"Голос учтен: YES={yes_cnt}/{need}")
    return

  if data.startswith("goto:"):
    # goto:{lobby_id}:{gid}:{uid}:{page}
    parts = data.split(":")
    if len(parts) != 5:
      await q.answer()
      return
    lobby_id, gid, uid, page = parts[1], parts[2], int(parts[3]), int(parts[4])
    if int(q.from_user.id) != uid:
      await q.answer("Это не твоя кнопка")
      return

    state = _load_state()
    lobby = _get_lobby(state, lobby_id)
    if not lobby or lobby.get("stage") != "running":
      await q.answer("Игра не активна")
      return

    ps = _api_player_state(gid, uid)
    houses = int(lobby["settings"]["houses"])
    cur = int(ps.get("location", 1))
    await BOT.send_message(uid, f"Выбор дома (стр {page})", reply_markup=_kb_goto_page(lobby_id, gid, uid, houses, page, cur))
    await q.answer("Ок")
    return

  if data.startswith("petmenu:"):
    # petmenu:{lobby_id}:{gid}:{uid}
    parts = data.split(":")
    if len(parts) != 4:
      await q.answer()
      return
    lobby_id, gid, uid = parts[1], parts[2], int(parts[3])
    if int(q.from_user.id) != uid:
      await q.answer("Это не твоя кнопка")
      return
    ps = _api_player_state(gid, uid)
    targets = ps.get("co_located_humans") or []
    if not targets:
      await q.answer("Нет живых игроков рядом")
      return
    await BOT.send_message(uid, "С кем обменяться питомцами? (нужно согласие второго игрока)", reply_markup=_kb_pet_targets(lobby_id, gid, uid, targets))
    await q.answer("Ок")
    return

  if data.startswith("act:"):
    # act:{lobby_id}:{gid}:{uid}:{kind} либо act:{lobby_id}:{gid}:{uid}:{kind}:{arg}
    parts = data.split(":")
    if len(parts) not in (5, 6):
      await q.answer()
      return
    lobby_id, gid, uid, kind = parts[1], parts[2], int(parts[3]), parts[4]
    arg = parts[5] if len(parts) == 6 else None

    if int(q.from_user.id) != uid:
      await q.answer("Это не твоя кнопка")
      return

    state = _load_state()
    lobby = _get_lobby(state, lobby_id)
    if not lobby or lobby.get("stage") != "running":
      await q.answer("Игра не активна")
      return

    humans = lobby.get("humans", {})
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
        await _do_step_and_next(lobby_id)
    except Exception as e:
      await q.answer("Ошибка")
      await BOT.send_message(uid, f"Ошибка action: {e}")
    return

  await q.answer()


async def main() -> None:
  _load_dotenv(ROOT_DIR / ".env")
  token = _env("BOT_TOKEN")

  global BOT
  BOT = Bot(token=token)

  dp = Dispatcher()
  dp.include_router(router)
  await dp.start_polling(BOT)


if __name__ == "__main__":
  asyncio.run(main())
