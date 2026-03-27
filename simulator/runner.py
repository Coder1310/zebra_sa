from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from simulator.engine import run_session


DEFAULT_LOG_DIR = Path("data/logs")


def load_config(path: str | None) -> dict[str, Any]:
  if path is None:
    return {}

  cfg_path = Path(path)
  with cfg_path.open("r", encoding="utf-8") as handle:
    return json.load(handle)


def parse_args() -> argparse.Namespace:
  parser = argparse.ArgumentParser()
  parser.add_argument("--session-id", default="manual")
  parser.add_argument("--config", type=str)
  parser.add_argument("--agents", type=int)
  parser.add_argument("--houses", type=int)
  parser.add_argument("--days", type=int)
  parser.add_argument("--share", type=str)
  parser.add_argument("--noise", type=float)
  parser.add_argument("--graph", type=str)
  parser.add_argument("--seed", type=int)
  parser.add_argument("--log-dir", default=str(DEFAULT_LOG_DIR))
  return parser.parse_args()


def merge_cli_into_config(cfg: dict[str, Any], args: argparse.Namespace) -> dict[str, Any]:
  merged = dict(cfg)
  for key in ("agents", "houses", "days", "share", "noise", "graph", "seed"):
    value = getattr(args, key)
    if value is not None:
      merged[key] = value
  return merged


def main() -> None:
  args = parse_args()
  cfg = merge_cli_into_config(load_config(args.config), args)
  log_dir = Path(args.log_dir)
  result = run_session(session_id=args.session_id, cfg=cfg, log_dir=log_dir)
  print(json.dumps({key: str(value) for key, value in result.items()}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
  main()
