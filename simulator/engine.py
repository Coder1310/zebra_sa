from __future__ import annotations

import csv
import random
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional


CATEGORIES = ("color", "nationality", "pet", "drink", "smoke")


@dataclass
class KnowledgeEntry:
  value: str
  day: int


@dataclass
class Trip:
  active: bool = False
  src: int = 1
  dst: int = 1
  remaining: int = 0
  start_event_id: int = 0


@dataclass
class Agent:
  name: str
  home: int
  location: int
  pet: str
  drink: str
  smoke: str
  trip: Trip = field(default_factory=Trip)
  knowledge: dict[tuple[int, str], KnowledgeEntry] = field(default_factory=dict)


@dataclass
class House:
  house_id: int
  color: str


def _clamp_int(x: Any, lo: int, hi: int) -> int:
  try:
    v = int(x)
  except Exception:
    return lo
  if v < lo:
    return lo
  if v > hi:
    return hi
  return v


def _norm_probs(probs: list[int]) -> list[int]:
  s = sum(max(0, int(x)) for x in probs)
  if s <= 0:
    n = len(probs)
    return [100 // n] * n
  out = []
  acc = 0
  for x in probs:
    p = max(0, int(x))
    v = int(round(100.0 * p / s))
    out.append(v)
    acc += v
  if acc != 100 and out:
    out[-1] += (100 - acc)
  return out


def _pick_by_probs(rng: random.Random, items: list[int], probs: list[int]) -> int:
  probs = _norm_probs(probs)
  r = rng.randint(1, 100)
  s = 0
  for item, p in zip(items, probs):
    s += p
    if r <= s:
      return item
  return items[-1]


def _zebra_defaults() -> dict[str, dict[str, Any]]:
  # Таблица 2.2 (в процентах)
  return {
    "Russian": {
      "p_to": [0, 20, 0, 20, 20, 40],
      "p_house_exch": 10,
      "p_pet_exch": 10,
    },
    "Englishman": {
      "p_to": [0, 0, 30, 30, 10, 30],
      "p_house_exch": 10,
      "p_pet_exch": 0,
    },
    "Chinese": {
      "p_to": [0, 0, 0, 30, 60, 10],
      "p_house_exch": 0,
      "p_pet_exch": 20,
    },
    "German": {
      "p_to": [0, 0, 0, 80, 10, 10],
      "p_house_exch": 10,
      "p_pet_exch": 10,
    },
    "French": {
      "p_to": [10, 20, 0, 0, 0, 70],
      "p_house_exch": 10,
      "p_pet_exch": 20,
    },
    "American": {
      "p_to": [10, 30, 0, 10, 10, 40],
      "p_house_exch": 10,
      "p_pet_exch": 10,
    },
  }


def _houses_default_6() -> list[House]:
  # Таблица 2.1: 1 Red, 2 Blue, 3 Yellow, 4 Green, 5 White, 6 Black
  colors = ["Red", "Blue", "Yellow", "Green", "White", "Black"]
  return [House(i + 1, colors[i]) for i in range(6)]


def _dist_ring(n: int) -> dict[tuple[int, int], int]:
  # Граф A: кольцо, прямые ребра только к соседям, расстояние 1
  dist = {}
  for i in range(1, n + 1):
    left = i - 1 if i > 1 else n
    right = i + 1 if i < n else 1
    dist[(i, left)] = 1
    dist[(i, right)] = 1
    dist[(i, i)] = 0
  return dist


def _dist_full_6() -> dict[tuple[int, int], int]:
  # Таблица 2.1 (B) как в PDF для 6 домов
  m = {
    (1, 1): 0, (1, 2): 1, (1, 3): 2, (1, 4): 3, (1, 5): 2, (1, 6): 2,
    (2, 1): 1, (2, 2): 0, (2, 3): 2, (2, 4): 2, (2, 5): 3, (2, 6): 2,
    (3, 1): 2, (3, 2): 2, (3, 3): 0, (3, 4): 1, (3, 5): 2, (3, 6): 3,
    (4, 1): 3, (4, 2): 2, (4, 3): 1, (4, 4): 0, (4, 5): 1, (4, 6): 2,
    (5, 1): 2, (5, 2): 3, (5, 3): 2, (5, 4): 1, (5, 5): 0, (5, 6): 2,
    (6, 1): 2, (6, 2): 2, (6, 3): 3, (6, 4): 2, (6, 5): 2, (6, 6): 0,
  }
  return m


def _observe_house(agent: Agent, day: int, house_id: int, houses: list[House], agents_by_home: dict[int, Agent]) -> None:
  house = houses[house_id - 1]
  resident = agents_by_home[house_id]
  facts = {
    "color": house.color,
    "nationality": resident.name,
    "pet": resident.pet,
    "drink": resident.drink,
    "smoke": resident.smoke,
  }
  for cat, val in facts.items():
    agent.knowledge[(house_id, cat)] = KnowledgeEntry(str(val), day)


def _observe_person(agent: Agent, day: int, other: Agent) -> None:
  # в модели это факты дома other.home, т.к. персональные атрибуты "едут" с человеком
  for cat, val in (("nationality", other.name), ("pet", other.pet), ("drink", other.drink), ("smoke", other.smoke)):
    agent.knowledge[(other.home, cat)] = KnowledgeEntry(str(val), day)


def _merge_knowledge(group: list[Agent]) -> None:
  merged: dict[tuple[int, str], KnowledgeEntry] = {}
  for a in group:
    for k, e in a.knowledge.items():
      cur = merged.get(k)
      if cur is None or e.day > cur.day:
        merged[k] = e
  for a in group:
    a.knowledge = dict(merged)


def _fact_value(house_id: int, cat: str, houses: list[House], agents_by_home: dict[int, Agent]) -> str:
  if cat == "color":
    return houses[house_id - 1].color
  resident = agents_by_home[house_id]
  if cat == "nationality":
    return resident.name
  if cat == "pet":
    return resident.pet
  if cat == "drink":
    return resident.drink
  if cat == "smoke":
    return resident.smoke
  return ""


def _m1(agent: Agent, houses: list[House], agents_by_home: dict[int, Agent]) -> float:
  total = len(houses) * len(CATEGORIES)
  ok = 0
  for hid in range(1, len(houses) + 1):
    for cat in CATEGORIES:
      e = agent.knowledge.get((hid, cat))
      if e is None:
        continue
      if e.value == _fact_value(hid, cat, houses, agents_by_home):
        ok += 1
  return ok / float(total)


def run_session(session_id: str, cfg: dict[str, Any], log_dir: Path) -> dict[str, Any]:
  log_dir.mkdir(parents=True, exist_ok=True)

  agents_n = int(cfg.get("agents", 6))
  houses_n = int(cfg.get("houses", 6))
  days = int(cfg.get("days", 50))

  share = str(cfg.get("share", "meet"))
  noise = float(cfg.get("noise", 0.0))
  seed = cfg.get("seed", None)

  graph = str(cfg.get("graph", "ring")).lower()
  use_zebra_defaults = bool(cfg.get("use_zebra_defaults", True))

  sleep_ms_per_day = _clamp_int(cfg.get("sleep_ms_per_day", 0), 0, 60_000)

  # стратегии:
  # - cfg["strategies"] - словарь name -> {p_to: [...], p_house_exch: int, p_pet_exch: int}
  # - mt_who + mt_strategy - как "override" для одного агента
  mt_who = cfg.get("mt_who", None)
  mt_strategy = cfg.get("mt_strategy", None)

  custom_strategies = cfg.get("strategies", None)
  if not isinstance(custom_strategies, dict):
    custom_strategies = {}

  rng = random.Random(seed)

  if houses_n == 6 and use_zebra_defaults:
    houses = _houses_default_6()
  else:
    houses = [House(i + 1, f"Color{i+1}") for i in range(houses_n)]

  if graph == "full" and houses_n == 6:
    dist = _dist_full_6()
  else:
    dist = _dist_ring(houses_n)

  # агенты
  if agents_n == 6 and houses_n == 6 and use_zebra_defaults:
    names = ["Russian", "Englishman", "Chinese", "German", "French", "American"]
    pets = ["Zebra", "Cat", "Dog", "Fox", "Horse", "Fish"]
    drinks = ["Tea", "Coffee", "Milk", "Water", "Juice", "Soda"]
    smokes = ["A", "B", "C", "D", "E", "F"]

    agents: list[Agent] = []
    for i, name in enumerate(names):
      hid = i + 1
      a = Agent(
        name=name,
        home=hid,
        location=hid,
        pet=pets[i],
        drink=drinks[i],
        smoke=smokes[i],
      )
      agents.append(a)
  else:
    agents = []
    for i in range(agents_n):
      hid = (i % houses_n) + 1
      a = Agent(
        name=f"a{i}",
        home=hid,
        location=hid,
        pet=f"p{i%houses_n}",
        drink=f"d{i%houses_n}",
        smoke=f"s{i%houses_n}",
      )
      agents.append(a)

  def agents_by_home() -> dict[int, Agent]:
    return {a.home: a for a in agents}

  defaults = _zebra_defaults()

  def strategy_for(a: Agent) -> dict[str, Any]:
    base = defaults.get(a.name, {"p_to": [100 // houses_n] * houses_n, "p_house_exch": 0, "p_pet_exch": 0})
    override = custom_strategies.get(a.name, {})
    if mt_who is not None and mt_strategy is not None and a.name == mt_who:
      override = dict(override)
      # mt_strategy может быть dict или pydantic-объект, приводим к dict
      try:
        override.update(dict(mt_strategy))
      except Exception:
        pass
    p_to = override.get("p_to", base.get("p_to", [100 // houses_n] * houses_n))
    if not isinstance(p_to, list) or len(p_to) != houses_n:
      p_to = base.get("p_to", [100 // houses_n] * houses_n)
      if len(p_to) != houses_n:
        p_to = [100 // houses_n] * houses_n
    p_to = _norm_probs([_clamp_int(x, 0, 100) for x in p_to])
    return {
      "p_to": p_to,
      "p_house_exch": _clamp_int(override.get("p_house_exch", base.get("p_house_exch", 0)), 0, 100),
      "p_pet_exch": _clamp_int(override.get("p_pet_exch", base.get("p_pet_exch", 0)), 0, 100),
    }

  # начальные знания: агент знает "свой дом" (5 фактов)
  for a in agents:
    _observe_house(a, 0, a.home, houses, agents_by_home())

  event_rows: list[list[str]] = []
  xml_events: list[dict[str, Any]] = []
  eid = 0

  def log_event(day: int, kind: str, *args: Any) -> int:
    nonlocal eid
    eid += 1
    row = [str(eid), str(day), str(kind)]
    row.extend("" if x is None else str(x) for x in args)
    event_rows.append(row)
    xml_events.append({"id": eid, "day": day, "type": kind, "args": ["" if x is None else str(x) for x in args]})
    return eid

  metrics_path = log_dir / f"metrics_{session_id}.csv"
  events_path = log_dir / f"game_{session_id}.csv"
  xml_path = log_dir / f"game_{session_id}.xml"

  with metrics_path.open("w", newline="", encoding="utf-8") as mf:
    w = csv.writer(mf)
    w.writerow(["day"] + [a.name for a in agents])

    for day in range(1, days + 1):
      if sleep_ms_per_day > 0:
        time.sleep(sleep_ms_per_day / 1000.0)

      by_home = agents_by_home()

      # 1) движение: уменьшаем remaining, фиксируем прибытия
      arrived: list[Agent] = []
      for a in agents:
        if not a.trip.active:
          continue
        a.trip.remaining -= 1
        if a.trip.remaining <= 0:
          a.trip.active = False
          a.location = a.trip.dst
          arrived.append(a)

      # 2) обработка прибытия: успех, если хозяин дома
      for a in arrived:
        dst = a.location
        host = by_home.get(dst)
        ok = 0
        if host is not None and (not host.trip.active) and host.location == dst:
          ok = 1
        if ok == 1:
          # встреча произойдет на шаге "share"
          pass
        else:
          # хозяина нет: возвращаемся обратно (как в PDF)
          a.location = a.trip.src
        log_event(day, "FinishTrip", a.trip.start_event_id, a.name, ok)

      # 3) обмены + запуск новых поездок
      by_home = agents_by_home()

      for a in agents:
        if a.trip.active:
          continue

        strat = strategy_for(a)
        p_house_exch = int(strat["p_house_exch"])
        p_pet_exch = int(strat["p_pet_exch"])

        # house exchange
        if rng.randint(1, 100) <= p_house_exch and len(agents) >= 2:
          n = 3 if (len(agents) >= 3 and rng.random() < 0.3) else 2
          picks = rng.sample(agents, n)
          homes_before = [x.home for x in picks]

          if n == 2:
            picks[0].home, picks[1].home = picks[1].home, picks[0].home
            log_event(day, "changeHouse", 2, picks[0].name, picks[1].name, homes_before[0], homes_before[1])
          else:
            # циклическая перестановка
            picks[0].home, picks[1].home, picks[2].home = homes_before[1], homes_before[2], homes_before[0]
            log_event(
              day,
              "changeHouse",
              3,
              picks[0].name,
              picks[1].name,
              picks[2].name,
              homes_before[0],
              homes_before[1],
              homes_before[2],
            )

          # участники сразу "видят" свои новые факты дома
          by_home = agents_by_home()
          for x in picks:
            _observe_house(x, day, x.home, houses, by_home)

        # pet exchange
        if rng.randint(1, 100) <= p_pet_exch and len(agents) >= 2:
          n = 3 if (len(agents) >= 3 and rng.random() < 0.3) else 2
          picks = rng.sample(agents, n)
          pets_before = [x.pet for x in picks]

          if n == 2:
            picks[0].pet, picks[1].pet = picks[1].pet, picks[0].pet
            log_event(day, "changePet", 2, picks[0].name, picks[1].name, pets_before[0], pets_before[1])
          else:
            picks[0].pet, picks[1].pet, picks[2].pet = pets_before[1], pets_before[2], pets_before[0]
            log_event(
              day,
              "changePet",
              3,
              picks[0].name,
              picks[1].name,
              picks[2].name,
              pets_before[0],
              pets_before[1],
              pets_before[2],
            )

          by_home = agents_by_home()
          for x in picks:
            _observe_house(x, day, x.home, houses, by_home)

        # поездка
        p_to = list(strat["p_to"])
        dst_candidates = list(range(1, houses_n + 1))

        # если граф A (кольцо), прямые поездки только к соседям/себе
        if graph != "full":
          left = a.location - 1 if a.location > 1 else houses_n
          right = a.location + 1 if a.location < houses_n else 1
          allowed = {a.location, left, right}
          dst_candidates = [h for h in dst_candidates if h in allowed]
          p_to = [p_to[h - 1] for h in dst_candidates]

        dst = _pick_by_probs(rng, dst_candidates, p_to)
        if dst == a.location:
          continue

        d = dist.get((a.location, dst), None)
        if d is None or d <= 0:
          continue

        a.trip.active = True
        a.trip.src = a.location
        a.trip.dst = dst
        a.trip.remaining = int(d)
        a.trip.start_event_id = log_event(day, "startTrip", a.name, a.location, dst)

      # 4) встречи и обмен знаниями (share=meet)
      if share == "meet":
        by_home = agents_by_home()
        groups: dict[int, list[Agent]] = {}
        for a in agents:
          if a.trip.active:
            continue
          groups.setdefault(a.location, []).append(a)

        for loc, group in groups.items():
          if len(group) < 2:
            continue

          # все видят факты дома, где находятся
          for a in group:
            _observe_house(a, day, loc, houses, by_home)

          # все видят друг друга (персональные атрибуты)
          for a in group:
            for b in group:
              if a is b:
                continue
              _observe_person(a, day, b)

          _merge_knowledge(group)

      # 5) шум: теряем 1 случайный факт
      if noise > 0.0:
        for a in agents:
          if rng.random() < noise and a.knowledge:
            k = rng.choice(list(a.knowledge.keys()))
            a.knowledge.pop(k, None)

      # 6) метрика M1
      by_home = agents_by_home()
      row = [day]
      for a in agents:
        row.append(f"{_m1(a, houses, by_home):.6f}")
      w.writerow(row)

  with events_path.open("w", newline="", encoding="utf-8") as ef:
    ef.write("eventID;day;event\n")
    for r in event_rows:
      ef.write(";".join(r) + "\n")

  _write_xml(xml_path, session_id=session_id, events=xml_events)

  return {
    "csv": events_path,
    "xml": xml_path,
    "metrics": metrics_path,
    "finished_at": time.time(),
  }


def _write_xml(path: Path, session_id: str, events: list[dict[str, Any]]) -> None:
  lines = []
  lines.append(f'<log session="{session_id}">')
  lines.append("  <events>")
  for e in events:
    eid = e["id"]
    day = e["day"]
    typ = e["type"]
    lines.append(f'    <event id="{eid}" day="{day}" type="{typ}">')
    for i, arg in enumerate(e.get("args", []), start=1):
      lines.append(f'      <arg i="{i}">{_xml_escape(str(arg))}</arg>')
    lines.append("    </event>")
  lines.append("  </events>")
  lines.append("</log>")
  path.write_text("\n".join(lines), encoding="utf-8")


def _xml_escape(s: str) -> str:
  return (
    s.replace("&", "&amp;")
    .replace("<", "&lt;")
    .replace(">", "&gt;")
    .replace('"', "&quot;")
    .replace("'", "&apos;")
  )
