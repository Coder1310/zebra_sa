from __future__ import annotations

from dataclasses import dataclass

from core.schema import BeliefSnapshot, TruthSnapshot


@dataclass(frozen = True)
class AgentMetrics:
  known_personal_facts: int
  correct_personal_facts: int
  total_personal_facts: int
  m1_personal: float

  zebra_owner_true: str | None
  zebra_owner_pred: str | None
  zebra_resolved: bool
  m2_zebra: int


def _true_zebra_owner(truth: TruthSnapshot) -> str | None:
  for person, pet in truth.person_pet.items():
    if pet == "Zebra":
      return person
  return None


def _predicted_zebra_owner(belief: BeliefSnapshot) -> str | None:
  owners = [person for person, pet in belief.person_pet.items() if pet == "Zebra"]
  if len(owners) == 1:
    return owners[0]

  if belief.zebra_owner_probs:
    best_person = None
    best_prob = None
    for person, prob in belief.zebra_owner_probs.items():
      p = float(prob)
      if best_prob is None or p > best_prob:
        best_prob = p
        best_person = person
    return best_person

  return None


def evaluate_agent(truth: TruthSnapshot, belief: BeliefSnapshot) -> AgentMetrics:
  persons = sorted(truth.person_home.keys())

  known = 0
  correct = 0
  total = len(persons) * 4

  for person in persons:
    if person in belief.person_home:
      known += 1
      if belief.person_home[person] == truth.person_home[person]:
        correct += 1

    if person in belief.person_pet:
      known += 1
      if belief.person_pet[person] == truth.person_pet[person]:
        correct += 1

    if person in belief.person_drink:
      known += 1
      if belief.person_drink[person] == truth.person_drink[person]:
        correct += 1

    if person in belief.person_smoke:
      known += 1
      if belief.person_smoke[person] == truth.person_smoke[person]:
        correct += 1

  m1 = (correct / total) if total > 0 else 0.0

  zebra_true = _true_zebra_owner(truth)
  zebra_pred = _predicted_zebra_owner(belief)
  zebra_resolved = zebra_pred is not None
  m2 = int(zebra_true is not None and zebra_pred == zebra_true)

  return AgentMetrics(
    known_personal_facts = known,
    correct_personal_facts = correct,
    total_personal_facts = total,
    m1_personal = m1,
    zebra_owner_true = zebra_true,
    zebra_owner_pred = zebra_pred,
    zebra_resolved = zebra_resolved,
    m2_zebra = m2,
  )