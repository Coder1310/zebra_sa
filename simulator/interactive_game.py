from __future__ import annotations

import csv
import random
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


@dataclass
class Action:
  kind: str  # stay | left | right | go_to | house_exchange | pet_exchange
  dst: Optional[int] = None


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
    if n == 0:
      return []
    base = 100 // n
    out = [base] * n
    out[-1] += 100 - sum(out)
    return out
  out: list[int] = []
  acc = 0
  for x in probs:
    p = max(0, int(x))
    v = int(round(100.0 * p / s))
    out.append(v)
    acc += v
  if out and acc != 100:
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
  return {
    "Russian": {"p_to": [0, 20, 0, 20, 20, 40], "p_house_exch": 10, "p_pet_exch": 10},
    "Englishman": {"p_to": [0, 0, 30, 30, 10, 30], "p_house_exch": 10, "p_pet_exch": 0},
    "Chinese": {"p_to": [0, 0, 0, 30, 60, 10], "p_house_exch": 0, "p_pet_exch": 20},
    "German": {"p_to": [0, 0, 0, 80, 10, 10], "p_house_exch": 10, "p_pet_exch": 10},
    "French": {"p_to": [10, 20, 0, 0, 0, 70], "p_house_exch": 10, "p_pet_exch": 20},
    "American": {"p_to": [10, 30, 0, 10, 10, 40], "p_house_exch": 10, "p_pet_exch": 10},
  }


def _houses_default_6() -> list[House]:
  colors = ["Red", "Blue", "Yellow", "Green", "White", "Black"]
  return [House(i + 1, colors[i]) for i in range(6)]


def _dist_ring(n: int) -> dict[tuple[int, int], int]:
  dist: dict[tuple[int, int], int] = {}
  for i in range(1, n + 1):
    left = i - 1 if i > 1 else n
    right = i + 1 if i < n else 1
    dist[(i, left)] = 1
    dist[(i, right)] = 1
    dist[(i, i)] = 0
  return dist


def _dist_full_6() -> dict[tuple[int, int], int]:
  return {
    (1, 1): 0, (1, 2): 1, (1, 3): 2, (1, 4): 3, (1, 5): 2, (1, 6): 2,
    (2, 1): 1, (2, 2): 0, (2, 3): 2, (2, 4): 2, (2, 5): 3, (2, 6): 2,
    (3, 1): 2, (3, 2): 2, (3, 3): 0, (3, 4): 1, (3, 5): 2, (3, 6): 3,
    (4, 1): 3, (4, 2): 2, (4, 3): 1, (4, 4): 0, (4, 5): 1, (4, 6): 2,
    (5, 1): 2, (5, 2): 3, (5, 3): 2, (5, 4): 1, (5, 5): 0, (5, 6): 2,
    (6, 1): 2, (6, 2): 2, (6, 3): 3, (6, 4): 2, (6, 5): 2, (6, 6): 0,
  }


def _observe_house(agent: Agent, day: int, house_id: int, houses: list[House], by_home: dict[int, Agent]) -> None:
  house = houses[house_id - 1]
  resident = by_home[house_id]
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


def _fact_value(house_id: int, cat: str, houses: list[House], by_home: dict[int, Agent]) -> str:
  if cat == "color":
    return houses[house_id - 1].color
  resident = by_home[house_id]
  if cat == "nationality":
    return resident.name
  if cat == "pet":
    return resident.pet
  if cat == "drink":
    return resident.drink
  if cat == "smoke":
    return resident.smoke
  return ""


def _m1(agent: Agent, houses: list[House], by_home: dict[int, Agent]) -> float:
  total = len(houses) * len(CATEGORIES)
  ok = 0
  for hid in range(1, len(houses) + 1):
    for cat in CATEGORIES:
      e = agent.knowledge.get((hid, cat))
      if e is None:
        continue
      if e.value == _fact_value(hid, cat, houses, by_home):
        ok += 1
  return ok / float(total)


def _xml_escape(s: str) -> str:
  return (
    s.replace("&", "&amp;")
     .replace("<", "&lt;")
     .replace(">", "&gt;")
     .replace('"', "&quot;")
     .replace("'", "&apos;")
  )


def _write_xml(path: Path, game_id: str, events: list[dict[str, Any]]) -> None:
  lines: list[str] = []
  lines.append(f'<log session="{game_id}">')
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


class InteractiveGame:
  def __init__(
    self,
    game_id: str,
    cfg: dict[str, Any],
    humans: dict[int, str],  # user_id -> agent_name (role)
    log_dir: Path,
  ) -> None:
    self.game_id = game_id
    self.log_dir = log_dir
    self.cfg = dict(cfg)
    self.humans = dict(humans)

    self.houses_n = int(cfg.get("houses", 6))
    self.agents_n = int(cfg.get("agents", 6))
    self.days_total = int(cfg.get("days", 50))
    self.graph = str(cfg.get("graph", "ring")).lower()
    self.share = str(cfg.get("share", "meet"))
    self.noise = float(cfg.get("noise", 0.0))

    seed = cfg.get("seed", None)
    self.rng = random.Random(seed)

    self.defaults = _zebra_defaults()
    self.custom_strategies = cfg.get("strategies") if isinstance(cfg.get("strategies"), dict) else {}

    if self.houses_n == 6:
      self.houses = _houses_default_6()
    else:
      self.houses = [House(i + 1, f"Color{i+1}") for i in range(self.houses_n)]

    if self.graph == "full" and self.houses_n == 6:
      self.dist = _dist_full_6()
    else:
      self.dist = _dist_ring(self.houses_n)

    self.day = 1
    self.event_id = 0
    self.events: list[list[str]] = []
    self.xml_events: list[dict[str, Any]] = []
    self.metrics_rows: list[list[str]] = []

    self.pending_actions: dict[str, Action] = {}

    self.agents = self._init_agents()
    self._init_knowledge()

    self.finished = False
    self.finished_result: Optional[dict[str, Any]] = None

  def _init_agents(self) -> list[Agent]:
    if self.agents_n == 6 and self.houses_n == 6:
      names = ["Russian", "Englishman", "Chinese", "German", "French", "American"]
      pets = ["Zebra", "Cat", "Dog", "Fox", "Horse", "Fish"]
      drinks = ["Tea", "Coffee", "Milk", "Water", "Juice", "Soda"]
      smokes = ["A", "B", "C", "D", "E", "F"]
      out: list[Agent] = []
      for i, name in enumerate(names):
        hid = i + 1
        out.append(Agent(name=name, home=hid, location=hid, pet=pets[i], drink=drinks[i], smoke=smokes[i]))
      return out

    out = []
    for i in range(self.agents_n):
      hid = (i % self.houses_n) + 1
      out.append(Agent(name=f"a{i}", home=hid, location=hid, pet=f"p{i}", drink=f"d{i}", smoke=f"s{i}"))
    return out

  def _by_home(self) -> dict[int, Agent]:
    return {a.home: a for a in self.agents}

  def _log_event(self, day: int, kind: str, *args: Any) -> int:
    self.event_id += 1
    row = [str(self.event_id), str(day), str(kind)]
    row.extend("" if x is None else str(x) for x in args)
    self.events.append(row)
    self.xml_events.append({
      "id": self.event_id,
      "day": day,
      "type": kind,
      "args": ["" if x is None else str(x) for x in args],
    })
    return self.event_id

  def _strategy_for(self, agent: Agent) -> dict[str, Any]:
    base = self.defaults.get(agent.name, {"p_to": [100 // self.houses_n] * self.houses_n, "p_house_exch": 0, "p_pet_exch": 0})
    override = self.custom_strategies.get(agent.name, {})
    p_to = override.get("p_to", base.get("p_to", [100 // self.houses_n] * self.houses_n))

    if (not isinstance(p_to, list)) or len(p_to) != self.houses_n:
      p_to = base.get("p_to", [100 // self.houses_n] * self.houses_n)
      if len(p_to) != self.houses_n:
        p_to = [100 // self.houses_n] * self.houses_n

    p_to = _norm_probs([_clamp_int(x, 0, 100) for x in p_to])

    return {
      "p_to": p_to,
      "p_house_exch": _clamp_int(override.get("p_house_exch", base.get("p_house_exch", 0)), 0, 100),
      "p_pet_exch": _clamp_int(override.get("p_pet_exch", base.get("p_pet_exch", 0)), 0, 100),
    }

  def _init_knowledge(self) -> None:
    by_home = self._by_home()
    for a in self.agents:
      _observe_house(a, 0, a.home, self.houses, by_home)

  def state(self) -> dict[str, Any]:
    by_home = self._by_home()
    m1s = {a.name: _m1(a, self.houses, by_home) for a in self.agents}
    pending_humans = []
    for uid, name in self.humans.items():
      if name not in self.pending_actions:
        pending_humans.append(uid)
    return {
      "game_id": self.game_id,
      "day": self.day,
      "days_total": self.days_total,
      "graph": self.graph,
      "pending_user_ids": pending_humans,
      "m1": m1s,
    }

  def set_action(self, user_id: int, action: Action) -> None:
    name = self.humans.get(user_id)
    if not name:
      return
    self.pending_actions[name] = action

  def finish_now(self) -> dict[str, Any]:
    if self.finished:
      return dict(self.finished_result or {"done": True, "files": None})

    by_home = self._by_home()
    m1s: list[float] = []
    for a in self.agents:
      m1s.append(_m1(a, self.houses, by_home))

    if not self.metrics_rows:
      self.metrics_rows.append(["day"] + [a.name for a in self.agents])

    last_day = max(0, self.day - 1)
    if len(self.metrics_rows) == 1 or self.metrics_rows[-1][0] != str(last_day):
      self.metrics_rows.append([str(last_day)] + [f"{x:.6f}" for x in m1s])

    files = self._finalize()
    leaderboard = sorted([(a.name, m1s[i]) for i, a in enumerate(self.agents)], key=lambda x: x[1], reverse=True)

    self.finished = True
    self.day = self.days_total + 1
    self.finished_result = {
      "done": True,
      "files": files,
      "day_finished": last_day,
      "leaderboard": leaderboard,
    }
    return dict(self.finished_result)

  def _neighbor_left(self, x: int) -> int:
    return x - 1 if x > 1 else self.houses_n

  def _neighbor_right(self, x: int) -> int:
    return x + 1 if x < self.houses_n else 1

  def _apply_exchange(self, day: int, kind: str, actor: Agent) -> None:
    others = [a for a in self.agents if a.name != actor.name and (not a.trip.active)]
    if not others:
      return
    b = self.rng.choice(others)

    if kind == "house":
      a_home, b_home = actor.home, b.home
      actor.home, b.home = b_home, a_home
      self._log_event(day, "changeHouse", 2, actor.name, b.name, a_home, b_home)
    else:
      a_pet, b_pet = actor.pet, b.pet
      actor.pet, b.pet = b_pet, a_pet
      self._log_event(day, "changePet", 2, actor.name, b.name, a_pet, b_pet)

    by_home = self._by_home()
    _observe_house(actor, day, actor.home, self.houses, by_home)
    _observe_house(b, day, b.home, self.houses, by_home)

  def _start_trip(self, day: int, agent: Agent, dst: int) -> None:
    if agent.trip.active:
      return
    if dst == agent.location:
      return
    d = self.dist.get((agent.location, dst), None)
    if d is None or d <= 0:
      return
    agent.trip.active = True
    agent.trip.src = agent.location
    agent.trip.dst = dst
    agent.trip.remaining = int(d)
    agent.trip.start_event_id = self._log_event(day, "startTrip", agent.name, agent.location, dst)

  def _bot_decision(self, agent: Agent) -> Action:
    strat = self._strategy_for(agent)

    if self.rng.randint(1, 100) <= int(strat["p_house_exch"]):
      return Action(kind="house_exchange")
    if self.rng.randint(1, 100) <= int(strat["p_pet_exch"]):
      return Action(kind="pet_exchange")

    p_to = list(strat["p_to"])
    dst_candidates = list(range(1, self.houses_n + 1))

    if self.graph != "full":
      left = self._neighbor_left(agent.location)
      right = self._neighbor_right(agent.location)
      allowed = [agent.location, left, right]
      dst_candidates = allowed
      p_to = [p_to[h - 1] for h in dst_candidates]

    dst = _pick_by_probs(self.rng, dst_candidates, p_to)
    if dst == agent.location:
      return Action(kind="stay")
    if self.graph != "full":
      if dst == self._neighbor_left(agent.location):
        return Action(kind="left")
      if dst == self._neighbor_right(agent.location):
        return Action(kind="right")
      return Action(kind="stay")
    return Action(kind="go_to", dst=dst)

  def step_day(self) -> dict[str, Any]:
    if self.finished:
      return dict(self.finished_result or {"done": True, "files": None})

    if self.day > self.days_total:
      return {"done": True, "files": None}

    day = self.day

    arrived: list[Agent] = []
    for a in self.agents:
      if not a.trip.active:
        continue
      a.trip.remaining -= 1
      if a.trip.remaining <= 0:
        a.trip.active = False
        a.location = a.trip.dst
        arrived.append(a)

    by_home = self._by_home()
    for a in arrived:
      dst = a.location
      host = by_home.get(dst)
      ok = 0
      if host is not None and (not host.trip.active) and host.location == dst:
        ok = 1
      if ok == 0:
        a.location = a.trip.src
      self._log_event(day, "FinishTrip", a.trip.start_event_id, a.name, ok)

    for a in self.agents:
      if a.trip.active:
        continue

      action = self.pending_actions.get(a.name)
      if action is None:
        action = self._bot_decision(a)

      if action.kind == "house_exchange":
        self._apply_exchange(day, "house", a)
        continue
      if action.kind == "pet_exchange":
        self._apply_exchange(day, "pet", a)
        continue

      if action.kind == "left":
        self._start_trip(day, a, self._neighbor_left(a.location))
        continue
      if action.kind == "right":
        self._start_trip(day, a, self._neighbor_right(a.location))
        continue
      if action.kind == "go_to" and action.dst is not None:
        if self.graph == "full":
          self._start_trip(day, a, int(action.dst))
        else:
          dst = int(action.dst)
          if dst in (self._neighbor_left(a.location), self._neighbor_right(a.location)):
            self._start_trip(day, a, dst)
        continue

    if self.share == "meet":
      by_home = self._by_home()
      groups: dict[int, list[Agent]] = {}
      for a in self.agents:
        if a.trip.active:
          continue
        groups.setdefault(a.location, []).append(a)

      for loc, group in groups.items():
        if len(group) < 2:
          continue
        for x in group:
          _observe_house(x, day, loc, self.houses, by_home)
        for x in group:
          for y in group:
            if x is y:
              continue
            _observe_person(x, day, y)
        _merge_knowledge(group)

    if self.noise > 0.0:
      for a in self.agents:
        if self.rng.random() < self.noise and a.knowledge:
          k = self.rng.choice(list(a.knowledge.keys()))
          a.knowledge.pop(k, None)

    by_home = self._by_home()
    m1s: list[float] = []
    for a in self.agents:
      m1s.append(_m1(a, self.houses, by_home))

    if not self.metrics_rows:
      self.metrics_rows.append(["day"] + [a.name for a in self.agents])
    self.metrics_rows.append([str(day)] + [f"{x:.6f}" for x in m1s])

    self.pending_actions = {}
    self.day += 1

    done = self.day > self.days_total
    files = None
    if done:
      files = self._finalize()

    leaderboard = sorted([(a.name, m1s[i]) for i, a in enumerate(self.agents)], key=lambda x: x[1], reverse=True)

    return {
      "done": done,
      "files": files,
      "day_finished": day,
      "leaderboard": leaderboard,
    }

  def _finalize(self) -> dict[str, str]:
    self.log_dir.mkdir(parents=True, exist_ok=True)

    metrics_path = self.log_dir / f"metrics_{self.game_id}.csv"
    events_path = self.log_dir / f"game_{self.game_id}.csv"
    xml_path = self.log_dir / f"game_{self.game_id}.xml"

    with metrics_path.open("w", newline="", encoding="utf-8") as f:
      w = csv.writer(f)
      for row in self.metrics_rows:
        w.writerow(row)

    with events_path.open("w", newline="", encoding="utf-8") as f:
      f.write("eventID;day;event\n")
      for r in self.events:
        f.write(";".join(r) + "\n")

    _write_xml(xml_path, self.game_id, self.xml_events)

    return {"metrics": str(metrics_path), "csv": str(events_path), "xml": str(xml_path)}
