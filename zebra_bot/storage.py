from __future__ import annotations

import time
from typing import Any, Optional

import yaml

from zebra_bot.config import BOT_STATE_PATH


def load_state() -> dict[str, Any]:
  if not BOT_STATE_PATH.exists():
    return {}
  try:
    return yaml.safe_load(BOT_STATE_PATH.read_text(encoding="utf-8")) or {}
  except Exception:
    return {}


def save_state(state: dict[str, Any]) -> None:
  BOT_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
  BOT_STATE_PATH.write_text(
    yaml.safe_dump(state, allow_unicode=True, sort_keys=False),
    encoding="utf-8",
  )


def ensure(state: dict[str, Any]) -> None:
  state.setdefault("games", {})
  state.setdefault("known_users", {})
  state.setdefault("draft", {})


def get_game(state: dict[str, Any], lobby_chat_id: int) -> Optional[dict[str, Any]]:
  ensure(state)
  return state["games"].get(str(lobby_chat_id))


def set_game(state: dict[str, Any], lobby_chat_id: int, game: Optional[dict[str, Any]]) -> None:
  ensure(state)
  key = str(lobby_chat_id)
  if game is None:
    state["games"].pop(key, None)
  else:
    state["games"][key] = game


def remember_user(state: dict[str, Any], user: Any) -> None:
  ensure(state)
  uid = int(user.id)
  username = (user.username or "").lower() or None
  state["known_users"][str(uid)] = {
    "name": user.full_name or "user",
    "username": username,
    "updated_at": int(time.time()),
  }


def user_id_by_username(state: dict[str, Any], username: str) -> Optional[int]:
  ensure(state)
  username = username.lower().lstrip("@")
  for uid_str, info in state["known_users"].items():
    if (info or {}).get("username") == username:
      return int(uid_str)
  return None


def draft_get(state: dict[str, Any], uid: int) -> Optional[dict[str, Any]]:
  ensure(state)
  return state["draft"].get(str(int(uid)))


def draft_set(state: dict[str, Any], uid: int, value: Optional[dict[str, Any]]) -> None:
  ensure(state)
  key = str(int(uid))
  if value is None:
    state["draft"].pop(key, None)
  else:
    state["draft"][key] = value


def mention(player: dict[str, Any]) -> str:
  u = player.get("username")
  if u:
    return f"@{u}"
  return player.get("name", "user")
