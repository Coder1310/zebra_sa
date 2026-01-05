from __future__ import annotations

import time
import uuid
from pathlib import Path
from typing import Any, Optional

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from simulator.engine import run_session


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

  graph: str = Field(default="ring")  # ring | full
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


app = FastAPI(title="Zebra SA Server")

_sessions: dict[str, dict[str, Any]] = {}


def _new_sid() -> str:
  return uuid.uuid4().hex[:12]


def _normalize_cfg(req: CreateSessionRequest) -> dict[str, Any]:
  cfg = req.model_dump()

  mt_strategy = cfg.get("mt_strategy")
  if isinstance(mt_strategy, BaseModel):
    cfg["mt_strategy"] = mt_strategy.model_dump()

  return cfg


def _save_session(sid: str, cfg: dict[str, Any]) -> None:
  _sessions[sid] = {
    "created_at": time.time(),
    "cfg": cfg,
    "done": False,
    "files": None,
  }


@app.get("/health")
def health() -> dict[str, str]:
  return {"status": "ok"}


@app.post("/session", response_model=CreateSessionResponse)
def create_session_alt(req: CreateSessionRequest) -> CreateSessionResponse:
  return create_session(req)


@app.post("/session/create", response_model=CreateSessionResponse)
def create_session(req: CreateSessionRequest) -> CreateSessionResponse:
  LOG_DIR.mkdir(parents=True, exist_ok=True)
  sid = _new_sid()
  cfg = _normalize_cfg(req)
  _save_session(sid, cfg)
  return CreateSessionResponse(session_id=sid)


def _run_and_return(sid: str) -> RunResponse:
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


@app.post("/session/{sid}/run", response_model=RunResponse)
def run_session_endpoint(sid: str) -> RunResponse:
  return _run_and_return(sid)


@app.post("/session/{sid}/start", response_model=RunResponse)
def start_session_endpoint(sid: str) -> RunResponse:
  return _run_and_return(sid)
