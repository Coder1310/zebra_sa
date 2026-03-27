from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = PROJECT_ROOT / "data"
LOGS_DIR = DATA_DIR / "logs"
STATE_PATH = DATA_DIR / "bot_state.json"


def _env_int(name: str, default: int) -> int:
  try:
    return int(os.getenv(name, str(default)).strip())
  except Exception:
    return default


def _env_float(name: str, default: float) -> float:
  try:
    return float(os.getenv(name, str(default)).strip())
  except Exception:
    return default


@dataclass(frozen=True)
class BotDefaults:
  players: int = _env_int("ZEBRA_PLAYERS", 6)
  houses: int = _env_int("ZEBRA_HOUSES", 6)
  days: int = _env_int("ZEBRA_DAYS", 50)
  share: str = os.getenv("ZEBRA_SHARE", "meet").strip() or "meet"
  noise: float = _env_float("ZEBRA_NOISE", 0.0)
  graph: str = os.getenv("ZEBRA_GRAPH", "ring").strip() or "ring"
  seed: int | None = None
  lobby_delay_sec: int = _env_int("ZEBRA_LOBBY_DELAY_SEC", 90)
  turn_delay_sec: int = _env_int("ZEBRA_TURN_DELAY_SEC", 60)
  vote_delay_sec: int = _env_int("ZEBRA_VOTE_DELAY_SEC", 45)


DEFAULTS = BotDefaults()


def BOT_TOKEN() -> str:
  return os.getenv("BOT_TOKEN", "").strip()


def api_base() -> str:
  return os.getenv("ZEBRA_API", "http://127.0.0.1:8000").strip()


def defaults_dict() -> dict[str, Any]:
  return {
    "players": DEFAULTS.players,
    "houses": DEFAULTS.houses,
    "days": DEFAULTS.days,
    "share": DEFAULTS.share,
    "noise": DEFAULTS.noise,
    "graph": DEFAULTS.graph,
    "seed": DEFAULTS.seed,
    "lobby_delay_sec": DEFAULTS.lobby_delay_sec,
    "turn_delay_sec": DEFAULTS.turn_delay_sec,
    "vote_delay_sec": DEFAULTS.vote_delay_sec,
    "strategies": None,
  }