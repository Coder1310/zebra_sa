from __future__ import annotations

import os
from dataclasses import asdict, dataclass
from pathlib import Path

from simulator.world import ROLES_6


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
LOGS_DIR = DATA_DIR / "logs"
BOT_STATE_PATH = LOGS_DIR / "bot_state.yaml"


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


def defaults_dict() -> dict:
  return asdict(DEFAULTS)


def load_dotenv(path: Path) -> None:
  if not path.exists():
    return
  for raw_line in path.read_text(encoding = "utf-8").splitlines():
    line = raw_line.strip()
    if not line or line.startswith("#") or "=" not in line:
      continue
    key, value = line.split("=", 1)
    key = key.strip()
    value = value.strip().strip('"').strip("'")
    if key and key not in os.environ:
      os.environ[key] = value


def env(name: str) -> str:
  value = os.getenv(name)
  if not value:
    raise RuntimeError(f"env {name} is required")
  return value


def api_base() -> str:
  return os.getenv("ZEBRA_API", "http://127.0.0.1:8000")