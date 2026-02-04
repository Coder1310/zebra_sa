from __future__ import annotations

import time

from zebra_bot.config import ROLES_6
from zebra_bot.storage import mention


def agent_names(agents: int, houses: int) -> list[str]:
  if agents == 6 and houses == 6:
    return list(ROLES_6)
  return [f"a{i}" for i in range(agents)]


def format_lobby(game: dict) -> str:
  players = game.get("players", {})
  need = int(game["settings"]["players"])
  cur = len(players)
  left = max(0, int(game["deadline_at"] - time.time()))
  invites = game.get("invited_usernames") or []

  lines: list[str] = []
  lines.append("🎮 ZEBRA: лобби")
  lines.append(f"Игроки: {cur}/{need}")
  for p in players.values():
    lines.append(f"- {mention(p)}")
  if invites:
    lines.append("")
    lines.append("Приглашены: " + " ".join(f"@{x}" for x in invites))
  lines.append(f"Старт через: {left} сек")
  lines.append("")
  lines.append("Нажми Join. Кто не успеет - будет заменен ботом.")
  return "\n".join(lines)


def render_player_info(ps: dict) -> str:
  if not ps.get("ok"):
    return f"Ошибка: {ps.get('reason')}"

  role = ps["role"]
  day = int(ps["day"])
  days_total = int(ps["days_total"])
  home = int(ps["home"])
  loc = int(ps["location"])
  m1 = float(ps.get("m1", 0.0))

  trip = ps.get("trip") or {}
  in_trip = bool(trip.get("active"))

  co_all = ps.get("co_located_all") or []
  offers = ps.get("pet_offers_in") or []

  lines: list[str] = []
  lines.append(f"🗓 День {day}/{days_total}")
  lines.append(f"Вы: {role}. Ваш дом: {home}. Сейчас: дом {loc}.")
  lines.append(f"Ваши атрибуты: pet={ps.get('pet')} drink={ps.get('drink')} smoke={ps.get('smoke')}")
  if in_trip:
    lines.append(f"Вы в пути: {trip.get('src')} -> {trip.get('dst')} (осталось {trip.get('remaining')} дн.)")
  if co_all:
    lines.append("В вашем доме сейчас: " + ", ".join(co_all))
  if offers:
    lines.append("Входящие предложения обмена питомцами: " + ", ".join(offers))
  lines.append(f"M1 сейчас: {m1:.3f}")

  know = ps.get("knowledge") or []
  rows: list[str] = []
  for r in know:
    hid = r["house"]
    parts = []
    for cat in ("color", "nationality", "pet", "drink", "smoke"):
      v = r.get(cat)
      parts.append(f"{cat}={v if v is not None else '?'}")
    rows.append(f"{hid}: " + " ".join(parts))

  table_text = "\n".join(rows)
  if len(table_text) > 2500:
    lines.append("")
    lines.append("Ваши знания по домам: (сокращено)")
    scored: list[tuple[int, str]] = []
    for r in know:
      cnt = sum(1 for cat in ("color", "nationality", "pet", "drink", "smoke") if r.get(cat) is not None)
      hid = r["house"]
      parts = []
      for cat in ("color", "nationality", "pet", "drink", "smoke"):
        v = r.get(cat)
        parts.append(f"{cat}={v if v is not None else '?'}")
      scored.append((cnt, f"{hid}: " + " ".join(parts)))
    scored.sort(reverse=True, key=lambda x: x[0])
    for _, line in scored[:10]:
      lines.append(line)
  else:
    lines.append("")
    lines.append("Ваши знания по домам:")
    lines.append(table_text)

  return "\n".join(lines)
