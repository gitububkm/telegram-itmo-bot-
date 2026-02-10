#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Скрипт для адаптации schedule.json:
- если у пары не указана аудитория или адрес, проставляет, что пара онлайн.
"""

import json
from pathlib import Path


def main() -> None:
    json_path = Path("schedule.json")
    if not json_path.exists():
        print("schedule.json not found")
        return

    with json_path.open("r", encoding="utf-8") as f:
        data = json.load(f)

    changed = False

    for week_key in ("odd", "even"):
        week = data.get(week_key, {})
        for day_name, classes in week.items():
            if not isinstance(classes, list):
                continue
            for cls in classes:
                if not isinstance(cls, dict):
                    continue

                room = cls.get("room")
                address = cls.get("address")

                # Если аудитории или адреса нет / пусто, считаем пару онлайн
                if not room or not address:
                    cls.setdefault("room", "онлайн")
                    cls.setdefault("address", "онлайн")
                    changed = True

    if not changed:
        print("No changes needed")
        return

    with json_path.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    print("schedule.json updated: missing room/address set to 'онлайн'")


if __name__ == "__main__":
    main()

