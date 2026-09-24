"""Чтение, проверка и атомарное сохранение пользовательских настроек."""

from copy import deepcopy
from datetime import date
import json
import os
from pathlib import Path
import tempfile
from uuid import uuid4


SCHEMA_VERSION = 1
MAX_RULES = 30


def new_rule(field="useragent", operator="Содержит", text=""):
    """Создать фильтр со стабильным идентификатором для ключей Streamlit."""
    return {"id": uuid4().hex, "field": field, "operator": operator, "text": text}


def default_state():
    return {
        "schema_version": SCHEMA_VERSION,
        "endpoint": "https://s3-private.mds.yandex.net",
        "bucket": "adfox-unload-imho-video",
        "prefix": "imho-video",
        "profile": "",
        "proxy": False,
        "keep_raw": True,
        "folder": str(Path.home() / "Downloads" / "adfox_logs"),
        "mode": "Скачать из S3",
        "local_path": "",
        "output_name": "filtered.tsv",
        "selected_date": date.today().isoformat(),
        "hour": 12,
        "rules": [
            new_rule("banner_id", "Одно из значений", "208684"),
            new_rule("flag_virtual", "Одно из значений", "0"),
        ],
    }


def state_path():
    """Вернуть пользовательский путь, не находящийся в репозитории."""
    override = os.environ.get("ADFOX_LOGS_STATE_FILE")
    if override:
        return Path(override).expanduser()
    if os.name == "nt":
        root = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
        return root / "AdFox Logs" / "state.json"
    if sys_platform() == "darwin":
        return Path.home() / "Library" / "Application Support" / "AdFox Logs" / "state.json"
    root = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return root / "adfox-logs" / "state.json"


def sys_platform():
    # Отдельная функция упрощает проверку выбора пути без изменения sys.platform.
    import sys
    return sys.platform


def _normalise_rule(raw, fields, operators, used_ids, recover):
    if not isinstance(raw, dict):
        if recover:
            return None
        raise ValueError("Некорректный фильтр")
    field, operator, text = raw.get("field"), raw.get("operator"), raw.get("text")
    if field not in fields or operator not in operators or not isinstance(text, str):
        if recover:
            return None
        raise ValueError("Некорректный фильтр")
    rule_id = raw.get("id")
    if not isinstance(rule_id, str) or not rule_id or rule_id in used_ids:
        rule_id = uuid4().hex
    used_ids.add(rule_id)
    return {"id": rule_id, "field": field, "operator": operator, "text": text}


def normalise_state(raw, defaults, fields, operators, recover=False):
    """Проверить настройки; в recover-режиме сохранить корректную их часть."""
    if not isinstance(raw, dict):
        raise ValueError("Настройки должны быть объектом JSON")
    result = deepcopy(defaults)
    warnings = []
    version = raw.get("schema_version", 0)
    if not isinstance(version, int) or version > SCHEMA_VERSION:
        warnings.append("версия файла настроек новее поддерживаемой")

    for key in ("endpoint", "bucket", "prefix", "profile", "folder", "local_path", "output_name"):
        if key not in raw:
            continue
        if isinstance(raw[key], str):
            result[key] = raw[key]
        elif recover:
            warnings.append(f"поле {key} пропущено")
        else:
            raise ValueError("Некорректные настройки")
    if "proxy" in raw:
        if isinstance(raw["proxy"], bool):
            result["proxy"] = raw["proxy"]
        elif recover:
            warnings.append("поле proxy пропущено")
        else:
            raise ValueError("Некорректная настройка proxy")
    if "keep_raw" in raw:
        if isinstance(raw["keep_raw"], bool):
            result["keep_raw"] = raw["keep_raw"]
        elif recover:
            warnings.append("поле keep_raw пропущено")
        else:
            raise ValueError("Некорректная настройка keep_raw")
    if "mode" in raw:
        if raw["mode"] in ("Скачать из S3", "Локальный файл"):
            result["mode"] = raw["mode"]
        elif recover:
            warnings.append("режим источника сброшен")
        else:
            raise ValueError("Некорректный режим источника")
    if "selected_date" in raw:
        try:
            result["selected_date"] = date.fromisoformat(raw["selected_date"]).isoformat()
        except (TypeError, ValueError):
            if recover:
                warnings.append("дата сброшена")
            else:
                raise ValueError("Некорректная дата") from None
    if "hour" in raw:
        if isinstance(raw["hour"], int) and not isinstance(raw["hour"], bool) and 0 <= raw["hour"] <= 23:
            result["hour"] = raw["hour"]
        elif recover:
            warnings.append("час сброшен")
        else:
            raise ValueError("Некорректный час")

    if "rules" in raw:
        rules_raw = raw["rules"]
        if not isinstance(rules_raw, list) or not 1 <= len(rules_raw) <= MAX_RULES:
            if recover:
                warnings.append("список фильтров сброшен")
            else:
                raise ValueError("Нужны от 1 до 30 фильтров")
        else:
            used_ids = set()
            rules = [
                rule for item in rules_raw
                if (rule := _normalise_rule(item, fields, operators, used_ids, recover)) is not None
            ]
            if rules:
                result["rules"] = rules
                if len(rules) != len(rules_raw):
                    warnings.append("часть некорректных фильтров пропущена")
            elif recover:
                warnings.append("список фильтров сброшен")
            else:
                raise ValueError("Нужны корректные фильтры")
    result["schema_version"] = SCHEMA_VERSION
    return result, "; ".join(dict.fromkeys(warnings)) or None


def load_state(path, defaults, fields, operators):
    path = Path(path)
    if not path.exists():
        return deepcopy(defaults), None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        state, warning = normalise_state(raw, defaults, fields, operators, recover=True)
        if warning:
            warning = "Часть сохранённых настроек не восстановлена: " + warning + "."
        return state, warning
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError):
        return deepcopy(defaults), "Файл сохранённых настроек повреждён. Использованы безопасные значения по умолчанию."


def save_state(path, state):
    """Атомарно записать JSON и удалить временный файл при любой ошибке."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", newline="\n", dir=path.parent,
            prefix=path.name + ".", suffix=".part", delete=False,
        ) as outgoing:
            temporary = Path(outgoing.name)
            json.dump(state, outgoing, ensure_ascii=False, indent=2)
            outgoing.write("\n")
            outgoing.flush()
            os.fsync(outgoing.fileno())
        os.replace(temporary, path)
        temporary = None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def remove_rule(rules, rule_id):
    """Удалить выбранный фильтр, сохранив порядок и данные остальных."""
    if len(rules) <= 1:
        raise ValueError("Нельзя удалить единственный фильтр")
    result = [deepcopy(rule) for rule in rules if rule.get("id") != rule_id]
    if len(result) == len(rules):
        raise KeyError(rule_id)
    return result
