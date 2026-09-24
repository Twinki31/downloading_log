"""Построчная обработка TSV без загрузки всего лога в память."""
from dataclasses import dataclass
from pathlib import Path
import gzip
import os
import tempfile

OPERATORS = ("Одно из значений", "Не входит в список", "Содержит", "Не содержит", "Пусто", "Не пусто")

@dataclass(frozen=True)
class Rule:
    field: str
    operator: str
    values: tuple[str, ...] = ()

    def matches(self, value):
        if self.operator == "Одно из значений": return value in self.values
        if self.operator == "Не входит в список": return value not in self.values
        if self.operator == "Содержит": return any(x in value for x in self.values)
        if self.operator == "Не содержит": return not any(x in value for x in self.values)
        if self.operator == "Пусто": return value == ""
        if self.operator == "Не пусто": return value != ""
        raise ValueError("Неизвестное условие")

def filter_log(source, destination, rules, progress=None):
    source, destination = Path(source).expanduser(), Path(destination).expanduser()
    if source.resolve() == destination.resolve():
        raise ValueError("Исходный и итоговый файлы должны различаться")
    if not rules:
        raise ValueError("Добавьте хотя бы один фильтр")
    for rule in rules:
        if rule.operator not in OPERATORS:
            raise ValueError("Неизвестное условие")
        if rule.operator not in ("Пусто", "Не пусто") and not rule.values:
            raise ValueError(f"Укажите значения для {rule.field}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    checked = matched = malformed = 0
    preview = []
    opener = gzip.open if source.suffix == ".gz" else open
    try:
        with opener(source, "rt", encoding="utf-8-sig", newline="") as incoming:
            first = incoming.readline()
            if not first:
                raise ValueError("Лог пуст")
            headers = first.rstrip("\r\n").split("\t")
            if len(headers) != len(set(headers)):
                raise ValueError("В заголовке повторяются названия полей")
            missing = sorted({r.field for r in rules} - set(headers))
            if missing:
                raise ValueError("В логе отсутствуют поля: " + ", ".join(missing))
            indexed = [(headers.index(r.field), r) for r in rules]
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", newline="", dir=destination.parent, delete=False, suffix=".part") as outgoing:
                temporary = Path(outgoing.name)
                outgoing.write(first)
                for line in incoming:
                    checked += 1
                    cells = line.rstrip("\r\n").split("\t")
                    if len(cells) != len(headers):
                        malformed += 1
                    elif all(rule.matches(cells[index]) for index, rule in indexed):
                        outgoing.write(line)
                        matched += 1
                        if len(preview) < 50:
                            preview.append(dict(zip(headers, cells)))
                    if progress and checked % 100000 == 0:
                        progress(checked, matched)
            os.replace(temporary, destination)
            temporary = None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return {"checked": checked, "matched": matched, "malformed": malformed, "preview": preview}
