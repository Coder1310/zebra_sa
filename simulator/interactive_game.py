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
  kind: str
  dst: Optional[int] = None
  target: Optional[str] = None


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
    humans: dict[int, str],  # user_id -> agent_name
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

    # target -> set(offerers) для обмена питомцами (живые игроки)
    self.pet_offers: dict[str, set[str]] = {}

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

  def _by_name(self) -> dict[str, Agent]:
    return {a.name: a for a in self.agents}

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

  def _neighbor_left(self, x: int) -> int:
    return x - 1 if x > 1 else self.houses_n

  def _neighbor_right(self, x: int) -> int:
    return x + 1 if x < self.houses_n else 1

  def _remove_offers_from(self, offerer: str) -> None:
    for tgt, s in list(self.pet_offers.items()):
      if offerer in s:
        s.discard(offerer)
      if not s:
        self.pet_offers.pop(tgt, None)

  def _remove_offers_to(self, target: str) -> None:
    self.pet_offers.pop(target, None)

  def state(self) -> dict[str, Any]:
    by_home = self._by_home()
    m1s = {a.name: _m1(a, self.houses, by_home) for a in self.agents}
    # Важно: если человек в пути, от него не требуется действие на этот день.
    # Иначе игра может "зависнуть" в ожидании хода от игрока, который физически не может ходить.
    by_name = self._by_name()
    pending_humans: list[int] = []
    for uid, name in self.humans.items():
      a = by_name.get(name)
      if a is not None and a.trip.active:
        continue
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

  def player_state(self, user_id: int) -> dict[str, Any]:
    role = self.humans.get(int(user_id))
    if not role:
      return {"ok": False, "reason": "not a human in this game"}

    by_name = self._by_name()
    me = by_name.get(role)
    if me is None:
      return {"ok": False, "reason": "role not found"}

    by_home = self._by_home()
    m1 = _m1(me, self.houses, by_home)

    loc = me.location
    left = self._neighbor_left(loc)
    right = self._neighbor_right(loc)

    co_located_all: list[str] = []
    for a in self.agents:
      if a.name == me.name:
        continue
      if a.trip.active:
        continue
      if a.location == loc:
        co_located_all.append(a.name)

    human_roles = set(self.humans.values())
    co_located_humans = [x for x in co_located_all if x in human_roles]

    offers_in = sorted(list(self.pet_offers.get(me.name, set())))
    offers_in = [x for x in offers_in if x in human_roles]

    knowledge_rows: list[dict[str, Any]] = []
    for hid in range(1, self.houses_n + 1):
      row = {"house": hid}
      for cat in CATEGORIES:
        e = me.knowledge.get((hid, cat))
        row[cat] = e.value if e else None
      knowledge_rows.append(row)

    trip = {
      "active": bool(me.trip.active),
      "src": int(me.trip.src),
      "dst": int(me.trip.dst),
      "remaining": int(me.trip.remaining),
    }

    return {
      "ok": True,
      "role": me.name,
      "day": int(self.day),
      "days_total": int(self.days_total),
      "home": int(me.home),
      "location": int(me.location),
      "left_house": int(left),
      "right_house": int(right),
      "graph": self.graph,
      "trip": trip,
      "pet": me.pet,
      "drink": me.drink,
      "smoke": me.smoke,
      "m1": float(m1),
      "co_located_all": co_located_all,
      "co_located_humans": co_located_humans,
      "pet_offers_in": offers_in,
      "knowledge": knowledge_rows,
    }

  def set_action(self, user_id: int, action: Action) -> dict[str, Any]:
    name = self.humans.get(int(user_id))
    if not name:
      return {"ok": False, "reason": "not a human"}

    by_name = self._by_name()
    me = by_name.get(name)
    if me is None:
      return {"ok": False, "reason": "role not found"}

    kind = str(action.kind)

    # decline - это "операция над предложением", не фиксируем ход
    if kind == "pet_decline":
      offerer = (action.target or "").strip()
      if offerer:
        s = self.pet_offers.get(name)
        if s and offerer in s:
          s.discard(offerer)
          if not s:
            self.pet_offers.pop(name, None)
      return {"ok": True, "pending_user_ids": self.state()["pending_user_ids"]}

    # любое "обычное" действие игрока - отменяет его исходящие офферы (если передумал)
    self._remove_offers_from(name)

    if kind == "pet_offer":
      target = (action.target or "").strip()
      if not target:
        return {"ok": False, "reason": "no target"}

      target_agent = by_name.get(target)
      if target_agent is None:
        return {"ok": False, "reason": "bad target"}

      # только если оба стоят в одном доме и не в пути
      if me.trip.active or target_agent.trip.active:
        return {"ok": False, "reason": "someone is traveling"}
      if me.location != target_agent.location:
        return {"ok": False, "reason": "not in same house"}

      # только между живыми игроками
      if target not in set(self.humans.values()):
        return {"ok": False, "reason": "target is not a human player"}

      self.pet_offers.setdefault(target, set()).add(name)
      self.pending_actions[name] = Action(kind="pet_offer", target=target)
      return {"ok": True, "pending_user_ids": self.state()["pending_user_ids"]}

    if kind == "pet_accept":
      offerer = (action.target or "").strip()
      if not offerer:
        return {"ok": False, "reason": "no offerer"}
      self.pending_actions[name] = Action(kind="pet_accept", target=offerer)
      return {"ok": True, "pending_user_ids": self.state()["pending_user_ids"]}

    # обычные перемещения/ожидание
    self.pending_actions[name] = Action(kind=kind, dst=action.dst, target=action.target)
    return {"ok": True, "pending_user_ids": self.state()["pending_user_ids"]}

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
      "reports": {},
    }
    return dict(self.finished_result)

  def _apply_exchange_bot(self, day: int, kind: str, actor: Agent) -> Optional[tuple[str, str]]:
    # обмен ботами возможен только если в доме есть хотя бы 2 человека
    if actor.trip.active:
      return None
    same_loc = [a for a in self.agents if (not a.trip.active) and a.location == actor.location and a.name != actor.name]
    if not same_loc:
      return None
    b = self.rng.choice(same_loc)

    if kind == "house":
      a_home, b_home = actor.home, b.home
      actor.home, b.home = b_home, a_home
      self._log_event(day, "changeHouse", 2, actor.name, b.name, a_home, b_home)
      return (actor.name, b.name)

    a_pet, b_pet = actor.pet, b.pet
    actor.pet, b.pet = b_pet, a_pet
    self._log_event(day, "changePet", 2, actor.name, b.name, a_pet, b_pet)
    return (actor.name, b.name)

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
      return {"done": True, "files": None, "reports": {}}

    day = self.day

    # снимок знаний до дня - для отчета "сколько новых фактов"
    know_before = {a.name: set(a.knowledge.keys()) for a in self.agents}
    loc_before = {a.name: a.location for a in self.agents}

    arrived_ok_by_house: dict[int, list[str]] = {}

    # 1) завершаем поездки
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
      if ok == 1:
        arrived_ok_by_house.setdefault(dst, []).append(a.name)

    # 2) собираем действия (люди + боты)
    actions: dict[str, Action] = {}

    # люди
    for uid, role in self.humans.items():
      act = self.pending_actions.get(role)
      if act is not None:
        actions[role] = act

    # боты
    for a in self.agents:
      if a.name in actions:
        continue
      if a.trip.active:
        continue
      actions[a.name] = self._bot_decision(a)

    by_name = self._by_name()

    # 3) обмен питомцами по согласию (живые игроки)
    executed_pet_swaps: list[tuple[str, str]] = []
    for accepter, act in list(actions.items()):
      if act.kind != "pet_accept":
        continue
      offerer = (act.target or "").strip()
      if not offerer:
        continue
      offer_act = actions.get(offerer)
      if offer_act is None or offer_act.kind != "pet_offer":
        continue
      if (offer_act.target or "").strip() != accepter:
        continue

      a = by_name.get(offerer)
      b = by_name.get(accepter)
      if a is None or b is None:
        continue
      if a.trip.active or b.trip.active:
        continue
      if a.location != b.location:
        continue

      a_pet, b_pet = a.pet, b.pet
      a.pet, b.pet = b_pet, a_pet
      self._log_event(day, "changePet", 2, a.name, b.name, a_pet, b_pet)
      executed_pet_swaps.append((a.name, b.name))

      # после успешного обмена чистим офферы
      self._remove_offers_from(a.name)
      s = self.pet_offers.get(b.name)
      if s and a.name in s:
        s.discard(a.name)
        if not s:
          self.pet_offers.pop(b.name, None)

    # 4) обработка остальных действий
    started_trips: dict[str, int] = {}
    executed_house_swaps_bot: list[tuple[str, str]] = []
    executed_pet_swaps_bot: list[tuple[str, str]] = []

    for a in self.agents:
      if a.trip.active:
        continue
      act = actions.get(a.name)
      if act is None:
        continue

      if act.kind == "house_exchange":
        pair = self._apply_exchange_bot(day, "house", a)
        if pair:
          executed_house_swaps_bot.append(pair)
        continue

      if act.kind == "pet_exchange":
        pair = self._apply_exchange_bot(day, "pet", a)
        if pair:
          executed_pet_swaps_bot.append(pair)
        continue

      if act.kind == "pet_offer":
        # просто предложение - без движения
        continue

      if act.kind == "pet_accept":
        # принятие тоже без движения
        continue

      if act.kind == "stay":
        continue

      if act.kind == "left":
        dst = self._neighbor_left(a.location)
        self._start_trip(day, a, dst)
        started_trips[a.name] = dst
        continue

      if act.kind == "right":
        dst = self._neighbor_right(a.location)
        self._start_trip(day, a, dst)
        started_trips[a.name] = dst
        continue

      if act.kind == "go_to" and act.dst is not None:
        dst = int(act.dst)
        if self.graph == "full":
          self._start_trip(day, a, dst)
          started_trips[a.name] = dst
        else:
          if dst in (self._neighbor_left(a.location), self._neighbor_right(a.location)):
            self._start_trip(day, a, dst)
            started_trips[a.name] = dst
        continue

    # 5) встречи и обмен знаниями
    met_today: dict[str, list[str]] = {a.name: [] for a in self.agents}
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
          met_today[x.name] = [y.name for y in group if y.name != x.name]

        for x in group:
          _observe_house(x, day, loc, self.houses, by_home)
        for x in group:
          for y in group:
            if x is y:
              continue
            _observe_person(x, day, y)
        _merge_knowledge(group)

    # 6) шум
    if self.noise > 0.0:
      for a in self.agents:
        if self.rng.random() < self.noise and a.knowledge:
          k = self.rng.choice(list(a.knowledge.keys()))
          a.knowledge.pop(k, None)

    # 7) метрики
    by_home = self._by_home()
    m1s: list[float] = []
    m1_by_name: dict[str, float] = {}
    for a in self.agents:
      v = _m1(a, self.houses, by_home)
      m1s.append(v)
      m1_by_name[a.name] = v

    if not self.metrics_rows:
      self.metrics_rows.append(["day"] + [a.name for a in self.agents])
    self.metrics_rows.append([str(day)] + [f"{x:.6f}" for x in m1s])

    # 8) отчеты (повествование)
    reports: dict[str, list[str]] = {}
    total_facts = self.houses_n * len(CATEGORIES)

    for a in self.agents:
      lines: list[str] = []
      lines.append(f"День {day}/{self.days_total}")
      lines.append(f"Вы: {a.name}. Ваш дом: {a.home}. Сейчас: дом {a.location}.")

      if a.trip.active:
        lines.append(f"Вы отправились в дом {a.trip.dst} (осталось {a.trip.remaining} дн.).")
      elif a.name in started_trips:
        lines.append(f"Вы начали путь в дом {started_trips[a.name]}.")

      visitors = arrived_ok_by_house.get(loc_before.get(a.name, a.location), [])
      visitors = [x for x in visitors if x != a.name]
      if visitors:
        lines.append("К вам сегодня пришли: " + ", ".join(visitors) + ".")

      met = met_today.get(a.name, [])
      if met:
        lines.append("Сегодня вы встретили: " + ", ".join(met) + ".")

      # обмены питомцами по согласию
      for x, y in executed_pet_swaps:
        if a.name == x:
          lines.append(f"Обмен питомцами: вы обменялись с {y}.")
        if a.name == y:
          lines.append(f"Обмен питомцами: вы обменялись с {x}.")

      # бот-обмены (если были)
      for x, y in executed_pet_swaps_bot:
        if a.name == x:
          lines.append(f"Случайный обмен питомцами (бот): с {y}.")
        if a.name == y:
          lines.append(f"Случайный обмен питомцами (бот): с {x}.")
      for x, y in executed_house_swaps_bot:
        if a.name == x:
          lines.append(f"Случайный обмен домами (бот): с {y}.")
        if a.name == y:
          lines.append(f"Случайный обмен домами (бот): с {x}.")

      after_keys = set(a.knowledge.keys())
      new_keys = list(after_keys - know_before.get(a.name, set()))
      new_cnt = len(new_keys)
      known_cnt = len(after_keys)

      lines.append(f"Новых фактов сегодня: {new_cnt}. Известно фактов: {known_cnt}/{total_facts}.")
      lines.append(f"Текущий M1: {m1_by_name[a.name]:.3f}")

      reports[a.name] = lines

    # 9) чистим действия/офферы и идем дальше
    self.pending_actions = {}
    self.pet_offers = {}

    self.day += 1
    done = self.day > self.days_total

    files = None
    if done:
      files = self._finalize()

    leaderboard = sorted([(a.name, m1_by_name[a.name]) for a in self.agents], key=lambda x: x[1], reverse=True)

    return {
      "done": done,
      "files": files,
      "day_finished": day,
      "leaderboard": leaderboard,
      "reports": reports,
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
