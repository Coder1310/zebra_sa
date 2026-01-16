import argparse
import csv
import os
import time
from glob import glob

import requests


def _detect_delimiter(path: str) -> str:
  with open(path, "r", encoding = "utf-8") as f:
    line = f.readline()
  if line.count(";") >= line.count(","):
    return ";"
  return ","


def _read_metrics_series(path: str, who: str) -> list[tuple[int, float]]:
  delim = _detect_delimiter(path)
  out: list[tuple[int, float]] = []
  with open(path, "r", encoding = "utf-8", newline = "") as f:
    r = csv.DictReader(f, delimiter = delim)
    if not r.fieldnames or "day" not in r.fieldnames:
      raise RuntimeError(f"bad metrics header: {r.fieldnames}")
    if who not in r.fieldnames:
      raise RuntimeError(f"cannot find agent column '{who}' in: {r.fieldnames[:10]} ...")
    for row in r:
      out.append((int(float(row["day"])), float(row[who])))
  return out


def _tail_mean(series: list[tuple[int, float]], tail: int) -> float:
  if not series:
    return 0.0
  vals = [v for _, v in series[-min(tail, len(series)) :]]
  return sum(vals) / len(vals)


def _max_abs_diff(a: list[tuple[int, float]], b: list[tuple[int, float]]) -> float:
  da = {d: v for d, v in a}
  db = {d: v for d, v in b}
  days = sorted(set(da.keys()) & set(db.keys()))
  if not days:
    return 0.0
  return max(abs(da[d] - db[d]) for d in days)


def _list_metrics_files(logs_dir: str) -> list[str]:
  files: list[str] = []
  for p in (
    os.path.join(logs_dir, "metrics_*.csv"),
    os.path.join(logs_dir, "metrics-*.csv"),
    os.path.join(logs_dir, "metrics*.csv"),
  ):
    files.extend(glob(p))
  files = sorted(set(files), key=lambda x: os.path.getmtime(x) if os.path.exists(x) else 0.0)
  return files


def _parse_create_response(resp: requests.Response) -> str:
  try:
    j = resp.json()
    if isinstance(j, dict):
      sid = j.get("session_id") or j.get("sid") or j.get("id") or j.get("session")
      if sid:
        return str(sid)
  except Exception:
    pass
  t = (resp.text or "").strip().strip('"').strip("'")
  if t.startswith("{") and t.endswith("}"):
    try:
      import json
      d = json.loads(t)
      sid = d.get("session_id") or d.get("sid") or d.get("id") or d.get("session")
      if sid:
        return str(sid)
    except Exception:
      pass
  if not t:
    raise RuntimeError(f"cannot parse session id: {resp.text}")
  return t


def _create_session(api: str, cfg: dict) -> str:
  r = requests.post(f"{api}/session/create", json = cfg, timeout = 60)
  r.raise_for_status()
  return _parse_create_response(r)


def _run_until_metrics(api: str, sid: str, logs_dir: str, wait_sec: float) -> str:
  prev = set(_list_metrics_files(logs_dir))
  t_start = time.time()
  deadline = t_start + wait_sec
  last_info = None

  while time.time() < deadline:
    r = requests.post(f"{api}/session/{sid}/run", timeout = 60)
    r.raise_for_status()

    info = None
    try:
      info = r.json()
    except Exception:
      info = {"raw": r.text}

    last_info = info

    metrics_path = None
    if isinstance(info, dict):
      mp = info.get("metrics")
      if isinstance(mp, str) and mp.strip():
        metrics_path = mp.strip()

    if metrics_path:
      if os.path.exists(metrics_path) and os.path.getsize(metrics_path) > 0:
        return metrics_path
      alt = os.path.join(logs_dir, os.path.basename(metrics_path))
      if os.path.exists(alt) and os.path.getsize(alt) > 0:
        return alt

    files = _list_metrics_files(logs_dir)
    new_files = [
      f for f in files
      if f not in prev and os.path.getmtime(f) >= t_start - 0.2 and os.path.getsize(f) > 0
    ]
    if new_files:
      return max(new_files, key = os.path.getmtime)

    sleep_s = 0.2
    if isinstance(info, dict) and "deadline" in info:
      try:
        dl = float(info["deadline"])
        sleep_s = max(0.05, min(1.0, dl - time.time()))
      except Exception:
        pass
    time.sleep(sleep_s)

  raise RuntimeError(f"timeout waiting metrics sid = {sid}, last_info = {last_info}")


def _parse_mt_best(path: str) -> tuple[str, dict]:
  who = "a0"
  strat: dict = {}
  try:
    import yaml  # type: ignore
    with open(path, "r", encoding = "utf-8") as f:
      y = yaml.safe_load(f)
    if isinstance(y, dict):
      who = str(y.get("who", who))
      s = y.get("best_strategy")
      if isinstance(s, dict):
        strat = s
      return who, strat
  except Exception:
    pass

  cur = None
  with open(path, "r", encoding = "utf-8") as f:
    for raw in f:
      line = raw.rstrip("\n")
      if not line.strip():
        continue
      if line.startswith("who:"):
        who = line.split(":", 1)[1].strip()
      if line.startswith("best_strategy:"):
        cur = "best_strategy"
        continue
      if cur == "best_strategy" and line.startswith("  ") and ":" in line:
        k, v = line.strip().split(":", 1)
        v = v.strip()
        try:
          strat[k] = int(v)
        except Exception:
          try:
            strat[k] = float(v)
          except Exception:
            strat[k] = v
  return who, strat


def _override_variants(base_cfg: dict, who: str, strategy: dict) -> list[tuple[str, dict]]:
  return [
    ("mt_who + mt_strategy", {**base_cfg, "mt_who": who, "mt_strategy": strategy}),
    ("who + strategy", {**base_cfg, "who": who, "strategy": strategy}),
    ("overrides", {**base_cfg, "overrides": {who: strategy}}),
    ("strategy_overrides", {**base_cfg, "strategy_overrides": {who: strategy}}),
    ("player_overrides", {**base_cfg, "player_overrides": {who: strategy}}),
    ("agent_overrides", {**base_cfg, "agent_overrides": {who: strategy}}),
  ]


def main() -> None:
  p = argparse.ArgumentParser()
  p.add_argument("--api", default = "http://127.0.0.1:8000")
  p.add_argument("--out_dir", default = "data/logs")
  p.add_argument("--mt_best", default = "data/logs/mt_best.yaml")
  p.add_argument("--agents", type = int, default = 200)
  p.add_argument("--houses", type = int, default = 6)
  p.add_argument("--days", type = int, default = 200)
  p.add_argument("--share", default = "meet")
  p.add_argument("--noise", type = float, default = 0.2)
  p.add_argument("--seed", type = int, default = 1)
  p.add_argument("--wait", type = float, default = 600.0)
  p.add_argument("--tail", type = int, default = 50)
  args = p.parse_args()

  who, best_strategy = _parse_mt_best(args.mt_best)

  base_cfg = {
    "agents": args.agents,
    "houses": args.houses,
    "days": args.days,
    "share": args.share,
    "noise": args.noise,
    "seed": args.seed,
  }

  baseline_sid = _create_session(args.api, base_cfg)
  baseline_metrics = _run_until_metrics(args.api, baseline_sid, args.out_dir, args.wait)
  baseline_series = _read_metrics_series(baseline_metrics, who)

  chosen_schema = None
  mt_sid = None
  mt_metrics = None
  mt_series = None
  mt_diff = None

  for name, cfg in _override_variants(base_cfg, who, best_strategy):
    try:
      sid = _create_session(args.api, cfg)
      mpath = _run_until_metrics(args.api, sid, args.out_dir, args.wait)
      series = _read_metrics_series(mpath, who)
      diff = _max_abs_diff(baseline_series, series)

      chosen_schema = name
      mt_sid = sid
      mt_metrics = mpath
      mt_series = series
      mt_diff = diff
      break
    except Exception:
      continue

  if mt_sid is None or mt_metrics is None or mt_series is None or mt_diff is None:
    raise RuntimeError("cannot apply MT override with any known schema")

  baseline_final = baseline_series[-1][1]
  mt_final = mt_series[-1][1]
  baseline_tail = _tail_mean(baseline_series, args.tail)
  mt_tail = _tail_mean(mt_series, args.tail)
  identical = mt_diff == 0.0

  print(f"baseline_sid = {baseline_sid}")
  print(f"baseline_metrics = {baseline_metrics}")
  print(f"baseline_final = {baseline_final:.6f}")
  print(f"baseline_tail_mean(tail = {args.tail}) = {baseline_tail:.6f}")
  print(f"mt_sid = {mt_sid}")
  print(f"mt_metrics = {mt_metrics}")
  print(f"mt_final = {mt_final:.6f}")
  print(f"mt_tail_mean(tail={args.tail}) = {mt_tail:.6f}")
  print(f"series_identical = {identical}")
  print(f"override_schema = {chosen_schema}")
  print(f"diff_vs_baseline = {mt_diff:.6g}")

  try:
    import matplotlib.pyplot as plt
    x1 = [d for d, _ in baseline_series]
    y1 = [v for _, v in baseline_series]
    x2 = [d for d, _ in mt_series]
    y2 = [v for _, v in mt_series]

    plt.figure()
    plt.plot(x1, y1, label = "baseline")
    plt.plot(x2, y2, label = "mt")
    plt.xlabel("day")
    plt.ylabel(f"M1({who})")
    plt.grid(True)
    plt.legend()
    out_path = os.path.join(args.out_dir, "mt_effect_series.png")
    plt.savefig(out_path, dpi = 200, bbox_inches = "tight")
    print(f"saved {out_path}")
  except Exception as e:
    print(f"plot skipped: {e}")


if __name__ == "__main__":
  main()
