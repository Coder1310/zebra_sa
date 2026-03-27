from __future__ import annotations

from typing import Dict, List, Literal, Optional

from pydantic import BaseModel, Field


class VisiblePlayer(BaseModel):
  player_id: str
  house_id: int
  is_at_home: bool


class Event(BaseModel):
  event_id: int
  day: int
  type: str
  who: Optional[str] = None
  who1: Optional[str] = None
  who2: Optional[str] = None


class PlayerState(BaseModel):
  day: int
  player_id: str
  you: Dict[str, str]
  neighbors: Dict[str, int]
  visible_players: List[VisiblePlayer]
  events_since_last_turn: List[Event]


class BeliefState(BaseModel):
  houses: Dict[str, int] = Field(default_factory=dict)
  pets: Dict[str, str] = Field(default_factory=dict)
  drinks: Dict[str, str] = Field(default_factory=dict)
  smokes: Dict[str, str] = Field(default_factory=dict)

  def known_facts_count(self) -> int:
    return len(self.houses) + len(self.pets) + len(self.drinks) + len(self.smokes)


class Action(BaseModel):
  player_id: str
  day: int
  type: Literal["move", "stay", "trade_response"]
  direction: Optional[Literal["left", "right", "home"]] = None
  accept_house_swap: Optional[bool] = None
  accept_pet_swap: Optional[bool] = None
