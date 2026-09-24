"""Интерфейс приложения. Запуск: python -m streamlit run app.py"""
from datetime import date
from pathlib import Path
import json
import streamlit as st
from app_state import (MAX_RULES, default_state, load_state, new_rule,
                       normalise_state, remove_rule, save_state, state_path)
from fields import FIELDS, label
from filtering import OPERATORS, Rule
from download import download_log
from operations import process_local_log, process_s3_log

st.set_page_config(page_title="Логи AdFox", page_icon="📄", layout="wide")
st.title("Логи AdFox")
st.caption("Скачивание и фильтрация на вашем компьютере")

DEFAULTS = default_state()
STATE_FILE = state_path()


def clear_setting_widgets():
    prefixes = ("rule_field_", "rule_op_", "rule_text_", "delete_rule_")
    names = {"endpoint", "bucket", "prefix", "profile", "proxy", "keep_raw", "folder", "mode",
             "local_path", "selected_date", "hour", "output_name", "replace"}
    for key in list(st.session_state):
        if key in names or key.startswith(prefixes):
            del st.session_state[key]


if "settings" not in st.session_state:
    st.session_state.settings, st.session_state.state_warning = load_state(
        STATE_FILE, DEFAULTS, FIELDS, OPERATORS
    )
settings = st.session_state.settings
with st.sidebar:
    st.header("Настройки")
    if st.session_state.get("state_warning"):
        st.warning(st.session_state.pop("state_warning"))
    uploaded = st.file_uploader("Загрузить настройки JSON", type="json")
    if st.button("Применить настройки", disabled=uploaded is None):
        try:
            data = json.load(uploaded)
            merged, _ = normalise_state(data, DEFAULTS, FIELDS, OPERATORS)
            clear_setting_widgets()
            st.session_state.settings = merged
            save_state(STATE_FILE, merged)
            st.rerun()
        except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError):
            st.error("Не удалось прочитать настройки. Проверьте JSON и поля фильтров.")
    folder = st.text_input("Папка результатов", settings["folder"], key="folder")
    with st.expander("Подключение к S3"):
        endpoint = st.text_input("Адрес S3", settings["endpoint"], key="endpoint")
        bucket = st.text_input("Bucket", settings["bucket"], key="bucket")
        prefix = st.text_input("Папка в bucket", settings["prefix"], key="prefix")
        profile = st.text_input("AWS-профиль (пусто — стандартный)", settings["profile"], key="profile")
        proxy = st.checkbox("Использовать proxy из окружения", settings["proxy"], key="proxy")
    st.caption("Используется существующий AWS-профиль. Ключи доступа в настройки приложения не записываются.")
    st.caption(f"Рабочее состояние сохраняется автоматически: {STATE_FILE}")

mode_options = ["Скачать из S3", "Локальный файл"]
mode = st.radio("Источник", mode_options, index=mode_options.index(settings["mode"]), horizontal=True, key="mode")
keep_raw = st.checkbox(
    "Оставить сырой лог", settings["keep_raw"], key="keep_raw",
    disabled=mode != "Скачать из S3",
    help="Относится только к архивам .tsv.gz, скачанным приложением из S3.",
)
if mode == "Скачать из S3":
    st.caption("Если выключить флажок, новый архив удалится только после успешного сохранения итогового TSV.")
else:
    st.caption("Локальный исходный файл никогда не изменяется и не удаляется.")
if mode == "Скачать из S3":
    left, right = st.columns(2)
    selected_date = left.date_input("Дата в имени файла", date.fromisoformat(settings["selected_date"]), key="selected_date")
    hour = right.number_input("Час в имени файла", 0, 23, settings["hour"], key="hour")
    st.caption("Дата и час используются как есть, без преобразования часового пояса.")
else:
    local_path = st.text_input("Полный путь к файлу .tsv.gz или .tsv", settings["local_path"], key="local_path")

st.subheader("Фильтры")
st.caption("Все строки условий должны выполняться одновременно (И). Значения внутри одного фильтра — ИЛИ. Регистр учитывается.")
rules, saved_rules = [], []
delete_id = None
for i, default in enumerate(settings["rules"]):
    rule_id = default["id"]
    a, b, c, d = st.columns([2, 2, 3, 0.8])
    field = a.selectbox(f"Поле {i+1}", FIELDS, index=FIELDS.index(default["field"]), format_func=label, key=f"rule_field_{rule_id}")
    op = b.selectbox(f"Условие {i+1}", OPERATORS, index=OPERATORS.index(default["operator"]), key=f"rule_op_{rule_id}")
    raw = c.text_area(f"Значения {i+1} — каждое с новой строки", default["text"], height=90, key=f"rule_text_{rule_id}", disabled=op in ("Пусто", "Не пусто"))
    if d.button("Удалить", key=f"delete_rule_{rule_id}", disabled=len(settings["rules"]) <= 1,
                help=f"Удалить фильтр {i+1}"):
        delete_id = rule_id
    rules.append(Rule(field, op, tuple(x for x in raw.splitlines() if x != "")))
    saved_rules.append({"id": rule_id, "field": field, "operator": op, "text": raw})
add_rule = st.button("＋ Добавить фильтр", disabled=len(saved_rules) >= MAX_RULES)
st.info(" И ".join(f"{label(r.field)}: {r.operator.lower()}" + (f" [{'; '.join(r.values)}]" if r.operator not in ("Пусто", "Не пусто") else "") for r in rules))
st.caption("flag_virtual = 0 перенесён из исходного скрипта и теперь виден как обычный редактируемый фильтр. Неизвестные поля оставлены без выдуманных расшифровок.")
output_name = st.text_input("Имя результата", settings["output_name"], key="output_name")
replace = st.checkbox("Разрешить замену существующих файлов с теми же именами", key="replace")
export = dict(
    schema_version=settings["schema_version"], endpoint=endpoint, bucket=bucket,
    prefix=prefix, profile=profile, proxy=proxy, keep_raw=keep_raw, folder=folder, mode=mode,
    local_path=st.session_state.get("local_path", settings["local_path"]),
    output_name=output_name,
    selected_date=st.session_state.get("selected_date", date.fromisoformat(settings["selected_date"])).isoformat(),
    hour=int(st.session_state.get("hour", settings["hour"])), rules=saved_rules,
)
if delete_id is not None:
    export["rules"] = remove_rule(saved_rules, delete_id)
elif add_rule:
    export["rules"] = saved_rules + [new_rule()]

try:
    save_state(STATE_FILE, export)
    st.session_state.settings = export
except OSError as error:
    st.warning(f"Не удалось автоматически сохранить рабочее состояние: {error}")

if delete_id is not None or add_rule:
    clear_setting_widgets()
    st.session_state.settings = export
    st.rerun()

st.download_button("Сохранить настройки", json.dumps(export, ensure_ascii=False, indent=2), "adfox_settings.json", "application/json")

if st.button("Скачать и отфильтровать" if mode == "Скачать из S3" else "Отфильтровать", type="primary"):
    st.session_state.pop("result", None)
    archive = None
    try:
        if not folder.strip(): raise ValueError("Укажите папку результатов")
        if not output_name.endswith(".tsv") or Path(output_name).name != output_name:
            raise ValueError("Укажите имя файла с расширением .tsv без пути")
        for r in rules:
            if r.operator not in ("Пусто", "Не пусто") and not r.values:
                raise ValueError(f"Заполните значения для {label(r.field)}")
        destination = Path(folder).expanduser() / output_name
        if destination.exists() and not replace:
            raise ValueError("Результат уже существует: измените имя или разрешите замену")
        status = st.empty()
        if mode == "Скачать из S3":
            archive = Path(folder).expanduser() / f"{selected_date:%Y_%m_%d}_{hour:02d}.tsv.gz"
            if archive.exists() and not replace:
                raise ValueError("Архив уже существует. Выберите «Локальный файл» или разрешите замену")
            total = [0]
            def downloaded(size):
                total[0] += size
                status.info(f"Скачано: {total[0] / 1024**2:.1f} МБ")
            def download():
                return download_log(selected_date, hour, folder, endpoint, bucket, prefix, profile, proxy, downloaded)

            status.info("Скачивание…")
            result, archive_removed, existed_before = process_s3_log(
                archive, destination, rules, keep_raw, download,
                lambda n, m: status.info(f"Обработано: {n:,}. Найдено: {m:,}"),
            )
            if archive_removed:
                archive_note = "Скачанный архив удалён после успешного сохранения итогового TSV."
            elif existed_before and not keep_raw:
                archive_note = "Архив не удалён: он существовал до начала этой операции."
            else:
                archive_note = f"Сырой архив сохранён: {archive.resolve()}"
        else:
            if not local_path.strip(): raise ValueError("Укажите путь к логу")
            source = Path(local_path).expanduser()
            status.info("Фильтрация…")
            result = process_local_log(
                source, destination, rules,
                lambda n, m: status.info(f"Обработано: {n:,}. Найдено: {m:,}"),
            )
            archive_note = "Локальный исходный файл оставлен без изменений."
        status.empty()
        st.session_state.result = (str(destination.resolve()), result, archive_note)
    except Exception as error:
        st.error(f"Операция не завершена ({type(error).__name__}): {error}")
        if archive is not None and archive.exists():
            st.warning(f"Архив оставлен для диагностики или повторной обработки: {archive.resolve()}")
        st.caption("Проверьте путь, AWS-профиль и доступ к S3. Временные .part удаляются, а итоговый файл заменяется только после успешной обработки.")
if "result" in st.session_state:
    path, result, archive_note = st.session_state.result
    st.success(f"Готово: {path}")
    st.caption(archive_note)
    a, b, c = st.columns(3)
    a.metric("Обработано строк", result["checked"])
    b.metric("Найдено", result["matched"])
    c.metric("Некорректных строк", result["malformed"])
    if result["preview"]:
        st.caption("Первые 50 найденных строк. Полный результат сохранён на диске.")
        st.dataframe(result["preview"])
    else:
        st.info("Совпадений нет. Сохранён файл с заголовком.")
