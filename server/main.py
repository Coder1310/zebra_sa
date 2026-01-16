from __future__ import annotations

import time
import uuid
from pathlib import Path
from typing import Any, Optional

from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field

from simulator.engine import run_session
from simulator.interactive_game import InteractiveGame, Action


ROOT_DIR = Path(__file__).resolve().parents[1]
LOG_DIR = ROOT_DIR / "data" / "logs"


class MTStrategy(BaseModel):
  model_config = ConfigDict(extra="allow")
  p_to: Optional[list[int]] = None
  p_house_exch: Optional[int] = None
  p_pet_exch: Optional[int] = None


class CreateSessionRequest(BaseModel):
  model_config = ConfigDict(extra="allow")

  agents: int = Field(default=6, ge=1, le=20000)
  houses: int = Field(default=6, ge=2, le=50)
  days: int = Field(default=50, ge=1, le=20000)

  share: str = Field(default="meet")
  noise: float = Field(default=0.2, ge=0.0, le=1.0)
  seed: Optional[int] = None

  graph: str = Field(default="ring")
  use_zebra_defaults: bool = True

  strategies: Optional[dict[str, dict[str, Any]]] = None
  sleep_ms_per_day: int = Field(default=0, ge=0, le=60000)

  mt_who: Optional[str] = None
  mt_strategy: Optional[MTStrategy] = None


class CreateSessionResponse(BaseModel):
  session_id: str


class RunResponse(BaseModel):
  status: str
  session_id: str
  csv: str
  xml: str
  metrics: str
  finished_at: float


class HumanPlayer(BaseModel):
  user_id: int
  name: str
  role: str


class CreateGameRequest(BaseModel):
  model_config = ConfigDict(extra="allow")

  agents: int = Field(default=6, ge=3, le=20)
  houses: int = Field(default=6, ge=2, le=50)
  days: int = Field(default=50, ge=1, le=20000)

  share: str = Field(default="meet")
  noise: float = Field(default=0.2, ge=0.0, le=1.0)
  seed: Optional[int] = None

  graph: str = Field(default="ring")
  strategies: Optional[dict[str, dict[str, Any]]] = None

  humans: list[HumanPlayer]


class CreateGameResponse(BaseModel):
  game_id: str


class ActionRequest(BaseModel):
  user_id: int
  kind: str
  dst: Optional[int] = None
  target: Optional[str] = None


class StepResponse(BaseModel):
  game_id: str
  done: bool
  day_finished: Optional[int] = None
  leaderboard: Optional[list[list[Any]]] = None
  files: Optional[dict[str, str]] = None
  pending_user_ids: list[int] = []
  reports: Optional[dict[str, list[str]]] = None


class StateResponse(BaseModel):
  game_id: str
  day: int
  days_total: int
  graph: str
  pending_user_ids: list[int]
  m1: dict[str, float]


class PlayerStateResponse(BaseModel):
  ok: bool
  reason: Optional[str] = None

  role: Optional[str] = None
  day: Optional[int] = None
  days_total: Optional[int] = None
  home: Optional[int] = None
  location: Optional[int] = None
  left_house: Optional[int] = None
  right_house: Optional[int] = None
  graph: Optional[str] = None

  trip: Optional[dict[str, Any]] = None
  pet: Optional[str] = None
  drink: Optional[str] = None
  smoke: Optional[str] = None
  m1: Optional[float] = None

  co_located_all: Optional[list[str]] = None
  co_located_humans: Optional[list[str]] = None
  pet_offers_in: Optional[list[str]] = None

  knowledge: Optional[list[dict[str, Any]]] = None


app = FastAPI(title="Zebra SA Server")

_sessions: dict[str, dict[str, Any]] = {}
_games: dict[str, InteractiveGame] = {}


def _new_id() -> str:
  return uuid.uuid4().hex[:12]


@app.get("/health")
def health() -> dict[str, str]:
  return {"status": "ok"}


@app.post("/session/create", response_model=CreateSessionResponse)
def create_session(req: CreateSessionRequest) -> CreateSessionResponse:
  LOG_DIR.mkdir(parents=True, exist_ok=True)
  sid = _new_id()
  cfg = req.model_dump()
  _sessions[sid] = {"created_at": time.time(), "cfg": cfg, "done": False, "files": None}
  return CreateSessionResponse(session_id=sid)


@app.post("/session/{sid}/run", response_model=RunResponse)
def run_session_endpoint(sid: str) -> RunResponse:
  s = _sessions.get(sid)
  if s is None:
    raise HTTPException(status_code=404, detail="unknown session_id")

  if s["done"] and s["files"] is not None:
    files = s["files"]
    return RunResponse(
      status="done",
      session_id=sid,
      csv=str(files["csv"]),
      xml=str(files["xml"]),
      metrics=str(files["metrics"]),
      finished_at=float(files["finished_at"]),
    )

  cfg = dict(s["cfg"])
  files = run_session(session_id=sid, cfg=cfg, log_dir=LOG_DIR)

  s["done"] = True
  s["files"] = files

  return RunResponse(
    status="done",
    session_id=sid,
    csv=str(files["csv"]),
    xml=str(files["xml"]),
    metrics=str(files["metrics"]),
    finished_at=float(files["finished_at"]),
  )


@app.post("/game/create", response_model=CreateGameResponse)
def create_game(req: CreateGameRequest) -> CreateGameResponse:
  LOG_DIR.mkdir(parents=True, exist_ok=True)
  gid = _new_id()

  humans_map: dict[int, str] = {}
  for p in req.humans:
    humans_map[int(p.user_id)] = str(p.role)

  cfg = req.model_dump()
  game = InteractiveGame(game_id=gid, cfg=cfg, humans=humans_map, log_dir=LOG_DIR)
  _games[gid] = game

  return CreateGameResponse(game_id=gid)


@app.get("/game/{gid}/state", response_model=StateResponse)
def game_state(gid: str) -> StateResponse:
  game = _games.get(gid)
  if game is None:
    raise HTTPException(status_code=404, detail="unknown game_id")
  s = game.state()
  return StateResponse(
    game_id=s["game_id"],
    day=int(s["day"]),
    days_total=int(s["days_total"]),
    graph=str(s["graph"]),
    pending_user_ids=list(s["pending_user_ids"]),
    m1={k: float(v) for k, v in s["m1"].items()},
  )


@app.get("/game/{gid}/player_state", response_model=PlayerStateResponse)
def game_player_state(gid: str, user_id: int = Query(...)) -> PlayerStateResponse:
  game = _games.get(gid)
  if game is None:
    raise HTTPException(status_code=404, detail="unknown game_id")

  s = game.player_state(int(user_id))
  return PlayerStateResponse(**s)


@app.post("/game/{gid}/action")
def game_action(gid: str, req: ActionRequest) -> dict[str, Any]:
  game = _games.get(gid)
  if game is None:
    raise HTTPException(status_code=404, detail="unknown game_id")

  kind = str(req.kind)
  allowed = {
    "stay", "left", "right", "go_to",
    "house_exchange", "pet_exchange",
    "pet_offer", "pet_accept", "pet_decline",
  }
  if kind not in allowed:
    raise HTTPException(status_code=400, detail="bad action kind")

  res = game.set_action(int(req.user_id), Action(kind=kind, dst=req.dst, target=req.target))
  return res


@app.post("/game/{gid}/step", response_model=StepResponse)
def game_step(gid: str) -> StepResponse:
  game = _games.get(gid)
  if game is None:
    raise HTTPException(status_code=404, detail="unknown game_id")

  result = game.step_day()
  s2 = game.state() if not result.get("done") else {"pending_user_ids": []}

  return StepResponse(
    game_id=gid,
    done=bool(result.get("done")),
    day_finished=int(result.get("day_finished")) if result.get("day_finished") is not None else None,
    leaderboard=[[name, float(val)] for name, val in (result.get("leaderboard") or [])],
    files=result.get("files"),
    pending_user_ids=list(s2.get("pending_user_ids", [])),
    reports=result.get("reports") or {},
  )


@app.post("/game/{gid}/finish", response_model=StepResponse)
def game_finish(gid: str) -> StepResponse:
  game = _games.get(gid)
  if game is None:
    raise HTTPException(status_code=404, detail="unknown game_id")

  result = game.finish_now()

  return StepResponse(
    game_id=gid,
    done=True,
    day_finished=int(result.get("day_finished")) if result.get("day_finished") is not None else None,
    leaderboard=[[name, float(val)] for name, val in (result.get("leaderboard") or [])],
    files=result.get("files"),
    pending_user_ids=[],
    reports=result.get("reports") or {},
  )
