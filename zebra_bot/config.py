from __future__ import annotations

import os
from dataclasses import dataclass, asdict
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
LOGS_DIR = DATA_DIR / "logs"
BOT_STATE_PATH = LOGS_DIR / "bot_state.yaml"

ROLES_6 = ["Russian", "Englishman", "Chinese", "German", "French", "American"]


@dataclass
class Defaults:
  players: int = 6
  houses: int = 6
  days: int = 50
  share: str = "meet"
  noise: float = 0.2
  graph: str = "ring"  # ring | full
  lobby_delay_sec: int = 60
  turn_delay_sec: int = 30
  vote_delay_sec: int = 30


DEFAULTS = Defaults()


def defaults_dict() -> dict:
  return asdict(DEFAULTS)


def load_dotenv(path: Path) -> None:
  if not path.exists():
    return
  for raw in path.read_text(encoding = "utf-8").splitlines():
    line = raw.strip()
    if (not line) or line.startswith("#") or "=" not in line:
      continue
    k, v = line.split("=", 1)
    k = k.strip()
    v = v.strip().strip('"').strip("'")
    if k and k not in os.environ:
      os.environ[k] = v


def env(name: str) -> str:
  v = os.getenv(name)
  if not v:
    raise RuntimeError(f"env {name} is required")
  return v


def api_base() -> str:
  return os.getenv("ZEBRA_API", "http://127.0.0.1:8000")
