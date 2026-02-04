from __future__ import annotations

from typing import Any, Optional

import requests

from zebra_bot.config import api_base


def create_game(cfg: dict[str, Any]) -> str:
  r = requests.post(f"{api_base()}/game/create", json=cfg, timeout=60)
  r.raise_for_status()
  return r.json()["game_id"]


def state(gid: str) -> dict[str, Any]:
  r = requests.get(f"{api_base()}/game/{gid}/state", timeout=60)
  r.raise_for_status()
  return r.json()


def player_state(gid: str, user_id: int) -> dict[str, Any]:
  r = requests.get(f"{api_base()}/game/{gid}/player_state", params={"user_id": user_id}, timeout=60)
  r.raise_for_status()
  return r.json()


def action(gid: str, user_id: int, kind: str, dst: Optional[int] = None, target: Optional[str] = None) -> dict[str, Any]:
  payload = {"user_id": user_id, "kind": kind, "dst": dst, "target": target}
  r = requests.post(f"{api_base()}/game/{gid}/action", json=payload, timeout=60)
  r.raise_for_status()
  return r.json()


def step(gid: str) -> dict[str, Any]:
  r = requests.post(f"{api_base()}/game/{gid}/step", timeout=60 * 10)
  r.raise_for_status()
  return r.json()


def finish(gid: str) -> dict[str, Any]:
  r = requests.post(f"{api_base()}/game/{gid}/finish", timeout=60 * 10)
  r.raise_for_status()
  return r.json()
