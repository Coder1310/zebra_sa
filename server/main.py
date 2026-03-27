from __future__ import annotations

import time
import uuid
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from core.schema import Action
from simulator.engine import run_session
from simulator.interactive_game import InteractiveGame

APP_ROOT = Path(__file__).resolve().parents[1]
LOG_DIR = APP_ROOT / "data" / "logs"

app = FastAPI(title="Zebra Puzzle API")

_sessions: dict[str, dict[str, Any]] = {}
_games: dict[str, InteractiveGame] = {}


class SessionCreateRequest(BaseModel):
  agents: int = 6
  houses: int = 6
  days: int = 50
  share: str = "meet"
  noise: float = 0.0
  graph: str = "ring"
  seed: int | None = None
  sleep_ms_per_day: int = 0
  strategies: dict[str, Any] | None = None
  mt_who: str | None = None
  mt_strategy: dict[str, Any] | None = None


class ActionRequest(BaseModel):
  kind: str
  dst: int | None = None
  target: str | None = None


class GameCreateRequest(BaseModel):
  cfg: dict[str, Any] = Field(default_factory=dict)
  humans: dict[int, str] = Field(default_factory=dict)


class VoteRequest(BaseModel):
  user_id: int
  vote: str


def _now() -> float:
  return time.time()


def _new_id(prefix: str) -> str:
  return f"{prefix}_{uuid.uuid4().hex[:12]}"


def _normalize_cfg(cfg: dict[str, Any]) -> dict[str, Any]:
  out = dict(cfg)
  out.setdefault("agents", 6)
  out.setdefault("houses", 6)
  out.setdefault("days", 50)
  out.setdefault("share", "meet")
  out.setdefault("noise", 0.0)
  out.setdefault("graph", "ring")
  out.setdefault("seed", None)
  out.setdefault("sleep_ms_per_day", 0)
  return out


def _normalize_humans(raw: dict[int, str] | dict[str, str]) -> dict[int, str]:
  humans: dict[int, str] = {}
  for user_id, role in raw.items():
    humans[int(user_id)] = str(role)
  return humans


def _resolve_paths(files: dict[str, str] | dict[str, Path] | None) -> dict[str, str]:
  out: dict[str, str] = {}
  if not files:
    return out
  for key, value in files.items():
    out[str(key)] = str(value)
  return out


def _session_summary(session_id: str) -> dict[str, Any]:
  row = _sessions.get(session_id)
  if row is None:
    raise HTTPException(status_code=404, detail="session not found")

  return {
    "session_id": session_id,
    "created_at": row["created_at"],
    "finished_at": row.get("finished_at"),
    "cfg": row["cfg"],
    "done": row.get("done", False),
    "files": _resolve_paths(row.get("files")),
  }


def _game_summary(game_id: str) -> dict[str, Any]:
  game = _games.get(game_id)
  if game is None:
    raise HTTPException(status_code=404, detail="game not found")
  state = game.state()
  state["game_id"] = game_id
  return state


@app.get("/")
def root() -> dict[str, Any]:
  return {
    "ok": True,
    "service": "zebra-api",
    "sessions": len(_sessions),
    "games": len(_games),
  }


@app.get("/health")
def health() -> dict[str, Any]:
  return {"ok": True, "time": _now()}


@app.post("/session/new")
def create_session(req: SessionCreateRequest) -> dict[str, Any]:
  session_id = _new_id("session")
  cfg = _normalize_cfg(req.model_dump())

  _sessions[session_id] = {
    "session_id": session_id,
    "created_at": _now(),
    "cfg": cfg,
    "done": False,
    "files": {},
  }
  return _session_summary(session_id)


@app.get("/session/{session_id}")
def get_session(session_id: str) -> dict[str, Any]:
  return _session_summary(session_id)


@app.post("/session/{session_id}/run")
def run_saved_session(session_id: str) -> dict[str, Any]:
  row = _sessions.get(session_id)
  if row is None:
    raise HTTPException(status_code=404, detail="session not found")

  result = run_session(session_id, row["cfg"], LOG_DIR)
  row["done"] = True
  row["finished_at"] = result.get("finished_at", _now())
  row["files"] = result
  return _session_summary(session_id)


@app.post("/simulate")
def simulate(req: SessionCreateRequest) -> dict[str, Any]:
  session_id = _new_id("session")
  cfg = _normalize_cfg(req.model_dump())

  result = run_session(session_id, cfg, LOG_DIR)
  _sessions[session_id] = {
    "session_id": session_id,
    "created_at": _now(),
    "finished_at": result.get("finished_at", _now()),
    "cfg": cfg,
    "done": True,
    "files": result,
  }
  return {
    "ok": True,
    "session_id": session_id,
    "files": _resolve_paths(result),
  }


@app.post("/game/new")
def create_game(req: GameCreateRequest) -> dict[str, Any]:
  game_id = _new_id("game")
  cfg = _normalize_cfg(req.cfg)
  humans = _normalize_humans(req.humans)

  game = InteractiveGame(
    game_id=game_id,
    cfg=cfg,
    humans=humans,
    log_dir=LOG_DIR,
  )
  _games[game_id] = game

  return {
    "ok": True,
    "game_id": game_id,
    "cfg": cfg,
    "humans": humans,
    "state": game.state(),
  }


@app.get("/game/{game_id}")
def get_game(game_id: str) -> dict[str, Any]:
  return _game_summary(game_id)


@app.get("/game/{game_id}/state")
def get_game_state(game_id: str) -> dict[str, Any]:
  return _game_summary(game_id)


@app.get("/game/{game_id}/player/{user_id}")
def get_player_state(game_id: str, user_id: int) -> dict[str, Any]:
  game = _games.get(game_id)
  if game is None:
    raise HTTPException(status_code=404, detail="game not found")
  return game.player_state(user_id)


@app.post("/game/{game_id}/action/{user_id}")
def set_game_action(game_id: str, user_id: int, req: ActionRequest) -> dict[str, Any]:
  game = _games.get(game_id)
  if game is None:
    raise HTTPException(status_code=404, detail="game not found")
  return game.set_action(
    user_id,
    Action(kind=req.kind, dst=req.dst, target=req.target),
  )


@app.post("/game/{game_id}/step")
def step_game(game_id: str) -> dict[str, Any]:
  game = _games.get(game_id)
  if game is None:
    raise HTTPException(status_code=404, detail="game not found")
  result = game.step_day()
  if result.get("done"):
    result["files"] = _resolve_paths(result.get("files"))
  return result


@app.post("/game/{game_id}/finish")
def finish_game(game_id: str) -> dict[str, Any]:
  game = _games.get(game_id)
  if game is None:
    raise HTTPException(status_code=404, detail="game not found")
  result = game.finish_now()
  result["files"] = _resolve_paths(result.get("files"))
  return result


@app.delete("/game/{game_id}")
def delete_game(game_id: str) -> dict[str, Any]:
  game = _games.pop(game_id, None)
  if game is None:
    raise HTTPException(status_code=404, detail="game not found")
  return {"ok": True, "game_id": game_id}


@app.get("/debug/games")
def debug_games() -> dict[str, Any]:
  return {
    "ok": True,
    "games": list(_games.keys()),
  }


@app.get("/debug/sessions")
def debug_sessions() -> dict[str, Any]:
  return {
    "ok": True,
    "sessions": list(_sessions.keys()),
  }