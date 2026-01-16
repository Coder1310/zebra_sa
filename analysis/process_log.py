import argparse
import csv
import os
import re
from collections import defaultdict


def _detect_delimiter(path: str) -> str:
  candidates = [',', ';', '\t', '|']
  with open(path, 'r', encoding = 'utf-8') as f:
    for line in f:
      line = line.strip().lstrip('\ufeff')
      if not line:
        continue
      best = ','
      best_n = 1
      for d in candidates:
        n = len(line.split(d))
        if n > best_n:
          best_n = n
          best = d
      return best if best_n > 1 else ','
  return ','

def _to_int(x: str, default: int = 0) -> int:
  try:
    return int(float(str(x).strip().replace(",", ".")))
  except Exception:
    return default


def _to_float(x: str):
  try:
    return float(str(x).strip().replace(",", "."))
  except Exception:
    return None


def _ensure_dir(path: str) -> None:
  os.makedirs(path, exist_ok = True)


def _agent_to_nn(agent_name: str) -> str:
  m = re.fullmatch(r"a(\d+)", agent_name.strip())
  if m:
    return f"{int(m.group(1)) + 1:02d}"
  return "00"


def _write_awareness_csv(path: str, series: list[tuple[int, float | None]]) -> None:
  with open(path, "w", encoding = "utf-8", newline = "") as f:
    w = csv.writer(f, delimiter = ";")
    w.writerow(["day", "m1"])
    for day, v in series:
      w.writerow([day, "" if v is None else f"{v:.6g}"])


def _write_awareness_yaml(path: str, agent: str, series: list[tuple[int, float | None]]) -> None:
  with open(path, "w", encoding = "utf-8") as f:
    f.write(f"agent: {agent}\n")
    f.write("series:\n")
    for day, v in series:
      f.write(f"  - day: {day}\n")
      if v is None:
        f.write("    m1: null\n")
      else:
        f.write(f"    m1: {v:.6g}\n")


def _write_events_summary_yaml(path: str, events_csv: str) -> None:
  delim = _detect_delimiter(events_csv)
  counts: dict[str, int] = defaultdict(int)
  days_max = 0

  with open(events_csv, "r", encoding = "utf-8", newline = "") as f:
    r = csv.DictReader(f, delimiter = delim)
    for row in r:
      ev = (row.get("event") or row.get("Event") or "").strip()
      if ev:
        counts[ev] += 1
      d = _to_int(row.get("day") or row.get("Day") or "0", 0)
      if d > days_max:
        days_max = d

  with open(path, "w", encoding="utf-8") as f:
    f.write("events_summary:\n")
    f.write(f"  days_max: {days_max}\n")
    f.write("  counts:\n")
    for k in sorted(counts.keys()):
      f.write(f"    {k}: {counts[k]}\n")


def _is_long_format(fieldnames: list[str]) -> bool:
  low = {x.strip().lower() for x in fieldnames}
  return ("agent" in low or "player" in low or "name" in low) and ("m1" in low or "sa" in low)


def main() -> None:
  p = argparse.ArgumentParser()
  p.add_argument("--metrics", required = True, help = "metrics_*.csv")
  p.add_argument("--events", default = None, help = "game_*.csv (optional) -> events_summary.yaml")
  p.add_argument("--t", type = int, default = 500, help = "max day to export")
  p.add_argument("--out_dir", default = "data/logs")
  p.add_argument("--only_first", type = int, default = 0, help = "limit number of agents exported (0 = all)")
  args = p.parse_args()

  _ensure_dir(args.out_dir)

  delim = _detect_delimiter(args.metrics)
  with open(args.metrics, "r", encoding = "utf-8", newline = "") as f:
    r = csv.DictReader(f, delimiter = delim)
    if not r.fieldnames:
      raise SystemExit("empty metrics header")

    fieldnames = list(r.fieldnames)
    low_map = {x.strip().lower(): x for x in fieldnames}

    day_col = low_map.get("day")
    if day_col is None:
      raise SystemExit(f"no day column, columns = {fieldnames[:10]}...")

    if _is_long_format(fieldnames):
      agent_col = low_map.get("agent") or low_map.get("player") or low_map.get("name")
      m1_col = low_map.get("m1") or low_map.get("sa")

      by_agent: dict[str, list[tuple[int, float | None]]] = defaultdict(list)
      for row in r:
        day = _to_int(row.get(day_col, "0"), 0)
        if day <= 0 or day > args.t:
          continue
        agent = (row.get(agent_col, "") or "").strip()
        if not agent:
          continue
        v = _to_float(row.get(m1_col, ""))
        by_agent[agent].append((day, v))

      agents = sorted(by_agent.keys())
      if args.only_first and args.only_first > 0:
        agents = agents[:args.only_first]

      for agent in agents:
        series = by_agent[agent]
        nn = _agent_to_nn(agent)
        _write_awareness_csv(os.path.join(args.out_dir, f"awareness-{nn}.csv"), series)
        _write_awareness_yaml(os.path.join(args.out_dir, f"awareness-{nn}.yaml"), agent, series)

    else:
      agent_cols = [c for c in fieldnames if c != day_col]

      agent_cols.sort(key = lambda x: int(re.fullmatch(r"a(\d+)", x).group(1)) if re.fullmatch(r"a(\d+)", x) else 10**18)

      if args.only_first and args.only_first > 0:
        agent_cols = agent_cols[:args.only_first]

      series_map: dict[str, list[tuple[int, float | None]]] = {a: [] for a in agent_cols}

      for row in r:
        day = _to_int(row.get(day_col, "0"), 0)
        if day <= 0 or day > args.t:
          continue
        for a in agent_cols:
          series_map[a].append((day, _to_float(row.get(a, ""))))

      for a in agent_cols:
        nn = _agent_to_nn(a)
        _write_awareness_csv(os.path.join(args.out_dir, f"awareness-{nn}.csv"), series_map[a])
        _write_awareness_yaml(os.path.join(args.out_dir, f"awareness-{nn}.yaml"), a, series_map[a])

  if args.events:
    base = os.path.basename(args.events)
    out_yaml = os.path.join(args.out_dir, f"{os.path.splitext(base)[0]}_summary.yaml")
    _write_events_summary_yaml(out_yaml, args.events)

  print(f"ok: awareness files in {args.out_dir}")


if __name__ == "__main__":
  main()
