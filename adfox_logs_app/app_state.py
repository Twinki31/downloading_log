"""Чтение, проверка и атомарное сохранение пользовательских настроек."""

from copy import deepcopy
from datetime import date, datetime
import json
import os
from pathlib import Path
import tempfile
from urllib.parse import urlsplit, urlunsplit
from uuid import uuid4


SCHEMA_VERSION = 1
MAX_RULES = 30
MIN_SELECTED_DATE = date(2020, 1, 1)
ENDPOINT_USERINFO_MESSAGE = (
    "Адрес S3 не должен содержать имя пользователя, пароль или другие учётные данные. "
    "Доступ нужно настраивать через AWS-профиль, а не помещать учётные данные в адрес."
)
ENDPOINT_FORMAT_MESSAGE = (
    "Укажите корректный адрес S3: hostname, при необходимости порт и path; "
    "разрешены только http и https без query и fragment."
)


class EndpointValidationError(ValueError):
    """Безопасная ошибка endpoint, не содержащая исходное значение."""

    def __init__(self, message, *, has_userinfo=False):
        super().__init__(message)
        self.has_userinfo = has_userinfo


def normalise_s3_endpoint(value):
    """Проверить S3 endpoint и вернуть однозначный URL без учётных данных.

    Адрес без схемы считается HTTPS. Разрешены hostname (включая localhost),
    IPv4/IPv6, порт и абсолютный path. Query и fragment не являются частью
    endpoint и поэтому отклоняются.
    """
    if not isinstance(value, str):
        raise EndpointValidationError(ENDPOINT_FORMAT_MESSAGE)
    endpoint = value.strip()
    if not endpoint or any(character.isspace() for character in endpoint) or "\\" in endpoint:
        raise EndpointValidationError(ENDPOINT_FORMAT_MESSAGE)

    try:
        parsed = urlsplit(endpoint)
        scheme = parsed.scheme.lower()
        if scheme in ("http", "https"):
            if not parsed.netloc:
                raise EndpointValidationError(ENDPOINT_FORMAT_MESSAGE)
        elif parsed.netloc:
            # В том числе отклоняем protocol-relative форму //host: политика
            # требует либо явную схему, либо адрес, начинающийся с hostname.
            raise EndpointValidationError(ENDPOINT_FORMAT_MESSAGE)
        else:
            # Повторный разбор с authority-маркером даёт urllib.parse, а не
            # самодельному коду, отделить hostname, порт и возможный userinfo.
            parsed = urlsplit(f"//{endpoint}")
            scheme = "https"
        username = parsed.username
        password = parsed.password
        hostname = parsed.hostname
        port = parsed.port
    except ValueError:
        raise EndpointValidationError(ENDPOINT_FORMAT_MESSAGE) from None

    if username is not None or password is not None:
        raise EndpointValidationError(ENDPOINT_USERINFO_MESSAGE, has_userinfo=True)
    if not hostname:
        raise EndpointValidationError(ENDPOINT_FORMAT_MESSAGE)
    if parsed.query or parsed.fragment or port == 0:
        raise EndpointValidationError(ENDPOINT_FORMAT_MESSAGE)

    # urlsplit проверил скобки IPv6 и диапазон порта. Собираем netloc заново,
    # чтобы в нормализованное значение принципиально не мог попасть userinfo.
    host = f"[{hostname}]" if ":" in hostname else hostname
    netloc = host + (f":{port}" if port is not None else "")
    return urlunsplit((scheme, netloc, parsed.path, "", ""))


def new_rule(field="useragent", operator="Содержит", text=""):
    """Создать фильтр со стабильным идентификатором для ключей Streamlit."""
    return {"id": uuid4().hex, "field": field, "operator": operator, "text": text}


def default_state():
    now = datetime.now()
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
        "selected_date": now.date().isoformat(),
        "hour": now.hour,
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

    if "endpoint" in raw:
        try:
            result["endpoint"] = normalise_s3_endpoint(raw["endpoint"])
        except EndpointValidationError as error:
            # Учётные данные никогда не возвращаем вызывающему коду даже при
            # строгом импорте: безопасно сбрасываем только endpoint.
            if error.has_userinfo or recover:
                result["endpoint"] = defaults["endpoint"]
                warnings.append(str(error))
            else:
                raise

    for key in ("bucket", "prefix", "profile", "folder", "local_path", "output_name"):
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

    # Дата и час образуют один момент выбора, поэтому проверяем их вместе.
    # Это также не позволяет обойти ограничения интерфейса через JSON.
    selected_date = date.fromisoformat(result["selected_date"])
    now = datetime.now()
    if selected_date < MIN_SELECTED_DATE:
        if recover:
            result["selected_date"] = MIN_SELECTED_DATE.isoformat()
            warnings.append("дата ограничена 2020 годом")
        else:
            raise ValueError("Дата не может быть раньше 2020 года")
    elif selected_date > now.date():
        if recover:
            result["selected_date"] = now.date().isoformat()
            result["hour"] = now.hour
            warnings.append("будущая дата и час сброшены")
        else:
            raise ValueError("Нельзя выбрать будущую дату")
    elif selected_date == now.date() and result["hour"] > now.hour:
        if recover:
            result["hour"] = now.hour
            warnings.append("будущий час сброшен")
        else:
            raise ValueError("Нельзя выбрать будущий час")

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
    safe_state = deepcopy(state)
    if "endpoint" in safe_state:
        safe_state["endpoint"] = normalise_s3_endpoint(safe_state["endpoint"])
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", newline="\n", dir=path.parent,
            prefix=path.name + ".", suffix=".part", delete=False,
        ) as outgoing:
            temporary = Path(outgoing.name)
            json.dump(safe_state, outgoing, ensure_ascii=False, indent=2)
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
