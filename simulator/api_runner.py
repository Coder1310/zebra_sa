from __future__ import annotations

import argparse
import json
from typing import Any

import requests


def _post_json(base_url: str, path: str, payload: dict[str, Any], timeout: int = 600) -> dict[str, Any]:
  response = requests.post(
    f"{base_url.rstrip('/')}{path}",
    json=payload,
    timeout=timeout,
  )
  response.raise_for_status()
  data = response.json()
  if not isinstance(data, dict):
    raise RuntimeError(f"unexpected response for {path}")
  return data


def _get_json(base_url: str, path: str, timeout: int = 60) -> dict[str, Any]:
  response = requests.get(
    f"{base_url.rstrip('/')}{path}",
    timeout=timeout,
  )
  response.raise_for_status()
  data = response.json()
  if not isinstance(data, dict):
    raise RuntimeError(f"unexpected response for {path}")
  return data


def simulate(base_url: str, cfg: dict[str, Any]) -> dict[str, Any]:
  return _post_json(base_url, "/simulate", cfg)


def create_session(base_url: str, cfg: dict[str, Any]) -> dict[str, Any]:
  return _post_json(base_url, "/session/new", cfg)


def run_session_saved(base_url: str, session_id: str) -> dict[str, Any]:
  return _post_json(base_url, f"/session/{session_id}/run", {})


def build_arg_parser() -> argparse.ArgumentParser:
  parser = argparse.ArgumentParser(description="Run Zebra simulation through REST API")
  parser.add_argument("--base-url", default="http://127.0.0.1:8000")
  parser.add_argument("--mode", choices=["simulate", "session"], default="simulate")
  parser.add_argument("--agents", type=int, default=6)
  parser.add_argument("--houses", type=int, default=6)
  parser.add_argument("--days", type=int, default=50)
  parser.add_argument("--share", type=str, default="meet")
  parser.add_argument("--noise", type=float, default=0.0)
  parser.add_argument("--graph", type=str, default="ring")
  parser.add_argument("--seed", type=int, default=1)
  parser.add_argument("--sleep-ms-per-day", type=int, default=0)
  return parser


def main() -> None:
  args = build_arg_parser().parse_args()

  cfg = {
    "agents": args.agents,
    "houses": args.houses,
    "days": args.days,
    "share": args.share,
    "noise": args.noise,
    "graph": args.graph,
    "seed": args.seed,
    "sleep_ms_per_day": args.sleep_ms_per_day,
  }

  if args.mode == "simulate":
    result = simulate(args.base_url, cfg)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return

  created = create_session(args.base_url, cfg)
  session_id = str(created.get("session_id") or "")
  if not session_id:
    raise RuntimeError("server did not return session_id")

  result = run_session_saved(args.base_url, session_id)
  print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
  main()