from __future__ import annotations

from typing import Any

import requests

from zebra_bot.config import api_base


DEFAULT_TIMEOUT = 60.0
LONG_TIMEOUT = 600.0


class ApiError(RuntimeError):
  pass


def _request_json(method: str, path: str, *, json_data: dict[str, Any] | None = None,
                  params: dict[str, Any] | None = None, timeout: float = DEFAULT_TIMEOUT) -> dict[str, Any]:
  url = f"{api_base()}{path}"
  response = requests.request(method, url, json=json_data, params=params, timeout=timeout)
  try:
    response.raise_for_status()
  except requests.HTTPError as exc:
    body = response.text.strip()
    raise ApiError(f"{method} {path} failed: {response.status_code} {body}") from exc

  try:
    payload = response.json()
  except ValueError as exc:
    raise ApiError(f"{method} {path} returned non-JSON response") from exc

  if not isinstance(payload, dict):
    raise ApiError(f"{method} {path} returned unexpected payload: {payload!r}")
  return payload


def create_game(cfg: dict[str, Any]) -> str:
  payload = _request_json("POST", "/game/new", json_data=cfg)
  game_id = payload.get("game_id")
  if not isinstance(game_id, str) or not game_id:
    raise ApiError(f"/game/new did not return game_id: {payload}")
  return game_id


def state(gid: str) -> dict[str, Any]:
  return _request_json("GET", f"/game/{gid}/state")


def player_state(gid: str, user_id: int) -> dict[str, Any]:
  return _request_json("GET", f"/game/{gid}/player/{int(user_id)}")


def action(gid: str, user_id: int, kind: str, dst: int | None = None,
           target: str | None = None) -> dict[str, Any]:
  payload = {
    "kind": str(kind),
    "dst": dst,
    "target": target,
  }
  return _request_json("POST", f"/game/{gid}/action/{int(user_id)}", json_data=payload)


def step(gid: str) -> dict[str, Any]:
  return _request_json("POST", f"/game/{gid}/step", timeout=LONG_TIMEOUT)


def finish(gid: str) -> dict[str, Any]:
  return _request_json("POST", f"/game/{gid}/finish", timeout=LONG_TIMEOUT)
