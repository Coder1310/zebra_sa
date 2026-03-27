from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from zebra_bot.config import STATE_PATH


def _empty_state() -> dict[str, Any]:
  return {
    "games": {},
    "users": {},
    "drafts": {},
  }


def load_state() -> dict[str, Any]:
  path = Path(STATE_PATH)
  if not path.exists():
    return _empty_state()

  try:
    data = json.loads(path.read_text(encoding="utf-8"))
  except Exception:
    return _empty_state()

  if not isinstance(data, dict):
    return _empty_state()

  data.setdefault("games", {})
  data.setdefault("users", {})
  data.setdefault("drafts", {})
  return data


def save_state(state: dict[str, Any]) -> None:
  path = Path(STATE_PATH)
  path.parent.mkdir(parents=True, exist_ok=True)
  path.write_text(
    json.dumps(state, ensure_ascii=False, indent=2),
    encoding="utf-8",
  )


def get_game(state: dict[str, Any], chat_id: int) -> dict[str, Any] | None:
  games = state.setdefault("games", {})
  game = games.get(str(int(chat_id)))
  if isinstance(game, dict):
    return game
  return None


def set_game(state: dict[str, Any], chat_id: int, game: dict[str, Any] | None) -> None:
  games = state.setdefault("games", {})
  key = str(int(chat_id))
  if game is None:
    games.pop(key, None)
    return
  games[key] = game


def draft_get(state: dict[str, Any], user_id: int) -> dict[str, Any] | None:
  drafts = state.setdefault("drafts", {})
  value = drafts.get(str(int(user_id)))
  if isinstance(value, dict):
    return value
  return None


def draft_set(state: dict[str, Any], user_id: int, draft: dict[str, Any] | None) -> None:
  drafts = state.setdefault("drafts", {})
  key = str(int(user_id))
  if draft is None:
    drafts.pop(key, None)
    return
  drafts[key] = draft


def remember_user(state: dict[str, Any], user: Any) -> None:
  users = state.setdefault("users", {})
  uid = str(int(user.id))
  username = (getattr(user, "username", None) or "").strip().lower() or None
  full_name = (getattr(user, "full_name", None) or "").strip() or "user"

  row = users.get(uid)
  if not isinstance(row, dict):
    row = {}

  row["id"] = int(user.id)
  row["username"] = username
  row["full_name"] = full_name
  users[uid] = row


def user_id_by_username(state: dict[str, Any], username: str) -> int | None:
  target = (username or "").strip().lstrip("@").lower()
  if not target:
    return None

  users = state.setdefault("users", {})
  for uid, row in users.items():
    if not isinstance(row, dict):
      continue
    if (row.get("username") or "").lower() == target:
      try:
        return int(uid)
      except Exception:
        return None
  return None


def mention(user_row: dict[str, Any] | None) -> str:
  if not isinstance(user_row, dict):
    return "игрок"

  username = (user_row.get("username") or "").strip()
  if username:
    return f"@{username}"

  name = (user_row.get("name") or user_row.get("full_name") or "").strip()
  if name:
    return name

  uid = user_row.get("id")
  if uid is not None:
    return str(uid)

  return "игрок"