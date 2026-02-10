#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Генерация простого JSON-расписания по датам из `Текстовый документ.txt`.

Формат выходного JSON (schedule.json):
{
  "9.02": [
    {
      "subject": "...",
      "start": "09:50",
      "end": "11:20",
      "teacher": "...",
      "room": "311",
      "address": "Песочная наб., д.14, лит.А"
    }
  ],
  "10.02": [],
  ...
}
"""

import json
import re
from pathlib import Path


TEXT_FILE = Path("Текстовый документ.txt")
OUTPUT_JSON = Path("schedule.json")


DATE_RE = re.compile(r"^(\d{1,2}\.\d{2})$", re.MULTILINE)
TIME_RE = re.compile(r"^(\d{2}:\d{2})-(\d{2}:\d{2})$", re.MULTILINE)


def parse_schedule_by_date() -> dict:
    if not TEXT_FILE.exists():
        raise FileNotFoundError(f"{TEXT_FILE} not found")

    content = TEXT_FILE.read_text(encoding="utf-8")

    schedule: dict[str, list[dict]] = {}

    # Находим все вхождения дат
    date_matches = list(DATE_RE.finditer(content))

    for idx, m in enumerate(date_matches):
        date_str = m.group(1)  # например "9.02"
        start_pos = m.end()
        if idx + 1 < len(date_matches):
            end_pos = date_matches[idx + 1].start()
        else:
            end_pos = len(content)

        day_block = content[start_pos:end_pos]

        # Если указано, что день выходной
        if "выходной" in day_block.lower():
            schedule[date_str] = []
            continue

        classes: list[dict] = []

        # Находим все временные интервалы в этом дне
        time_matches = list(TIME_RE.finditer(day_block))
        for t_idx, t_match in enumerate(time_matches):
            start_time, end_time = t_match.group(1), t_match.group(2)
            seg_start = t_match.end()
            if t_idx + 1 < len(time_matches):
                seg_end = time_matches[t_idx + 1].start()
            else:
                seg_end = len(day_block)

            seg_text = day_block[seg_start:seg_end]
            lines = [ln.strip() for ln in seg_text.splitlines() if ln.strip()]
            if not lines:
                continue

            subject = lines[0]
            teacher = lines[1] if len(lines) > 1 else None
            room = lines[2] if len(lines) > 2 else None
            address = lines[3] if len(lines) > 3 else None

            # Нормализуем аудиторию и адрес
            if room and room.startswith("ауд."):
                room = room.replace("ауд.", "").strip()

            if not room:
                room = "онлайн"
            if not address:
                address = "онлайн"

            cls = {
                "subject": subject,
                "start": start_time,
                "end": end_time,
                "room": room,
                "address": address,
            }
            if teacher:
                cls["teacher"] = teacher

            classes.append(cls)

        schedule[date_str] = classes

    return schedule


def main() -> None:
    schedule = parse_schedule_by_date()
    OUTPUT_JSON.write_text(
        json.dumps(schedule, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"Готово. В schedule.json сохранено дней: {len(schedule)}")


if __name__ == "__main__":
    main()

