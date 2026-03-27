from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


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
  knowledge: dict[tuple[str, str], KnowledgeEntry] = field(default_factory=dict)


@dataclass
class Action:
  kind: str
  dst: Optional[int] = None
  target: Optional[str] = None


@dataclass(frozen=True)
class TruthSnapshot:
  house_color: dict[int, str]
  person_home: dict[str, int]
  person_pet: dict[str, str]
  person_drink: dict[str, str]
  person_smoke: dict[str, str]
  person_location: dict[str, int]


@dataclass
class BeliefSnapshot:
  house_color: dict[int, str] = field(default_factory=dict)
  house_resident: dict[int, str] = field(default_factory=dict)
  person_home: dict[str, int] = field(default_factory=dict)
  person_pet: dict[str, str] = field(default_factory=dict)
  person_drink: dict[str, str] = field(default_factory=dict)
  person_smoke: dict[str, str] = field(default_factory=dict)
  zebra_owner_probs: dict[str, float] = field(default_factory=dict)


@dataclass(frozen=True)
class AgentMetrics:
  known_personal_facts: int
  correct_personal_facts: int
  total_personal_facts: int
  m1_personal: float
  zebra_owner_true: str | None
  zebra_owner_pred: str | None
  zebra_resolved: bool
  m2_zebra: int