"""Интерфейс приложения. Запуск: python -m streamlit run app.py"""
from datetime import date
from functools import partial
from pathlib import Path
import json
import streamlit as st
from app_state import (MAX_RULES, default_state, load_state, new_rule,
                       normalise_state, remove_rule, save_state, state_path)
from fields import FIELDS, label
from filtering import OPERATORS, Rule
from execution import run_local_operation, run_s3_operation
from operation_state import OperationController

st.set_page_config(page_title="Логи AdFox", page_icon="📄", layout="wide")
st.title("Логи AdFox")
st.caption("Скачивание и фильтрация на вашем компьютере")

DEFAULTS = default_state()
STATE_FILE = state_path()

if "operation_controller" not in st.session_state:
    st.session_state.operation_controller = OperationController()
controller = st.session_state.operation_controller
operation_snapshot = controller.snapshot()
operation_active = operation_snapshot.active


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
    folder = st.text_input(
        "Папка результатов", settings["folder"], key="folder",
        disabled=operation_active,
    )
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
if mode == "Скачать из S3":
    left, right = st.columns(2)
    selected_date = left.date_input("Дата", date.fromisoformat(settings["selected_date"]), key="selected_date")
    hour = right.number_input("Час", 0, 23, settings["hour"], key="hour")
    st.caption("Дата и час используются как есть, без преобразования часового пояса.")
else:
    local_path = st.text_input("Полный путь к файлу .tsv.gz или .tsv", settings["local_path"], key="local_path")

st.subheader("Фильтры")
st.caption("Все строки условий должны выполняться одновременно (И). Значения внутри одного фильтра — ИЛИ. Регистр учитывается.")
if st.button("Подробное описание полей →"):
    st.switch_page("pages/1_Описание_полей.py")
st.markdown(
    """
    <style>
    div[class*='st-key-rule_text_'],
    div[class*='st-key-rule_text_'] [data-testid='stTextArea'],
    div[class*='st-key-rule_text_'] [data-testid='stTextAreaRootElement'] {
        height: auto !important;
        overflow: visible !important;
    }
    div[class*='st-key-rule_text_'] textarea {
        height: 2.375rem;
        min-height: 2.375rem !important;
        resize: vertical;
    }
    </style>
    """,
    unsafe_allow_html=True,
)
rules, saved_rules = [], []
delete_id = None
for i, default in enumerate(settings["rules"]):
    rule_id = default["id"]
    a, b, c, d = st.columns([2.7, 1.8, 3, 0.8])
    field = a.selectbox(f"Поле {i+1}", FIELDS, index=FIELDS.index(default["field"]), format_func=label, key=f"rule_field_{rule_id}")
    op = b.selectbox(f"Условие {i+1}", OPERATORS, index=OPERATORS.index(default["operator"]), key=f"rule_op_{rule_id}")
    raw = c.text_area(f"Значения {i+1} — каждое с новой строки", default["text"], key=f"rule_text_{rule_id}", disabled=op in ("Пусто", "Не пусто"))
    d.markdown("<div style='height: 1.75rem'></div>", unsafe_allow_html=True)
    if d.button("Удалить", key=f"delete_rule_{rule_id}", disabled=len(settings["rules"]) <= 1,
                help=f"Удалить фильтр {i+1}"):
        delete_id = rule_id
    rules.append(Rule(field, op, tuple(x for x in raw.splitlines() if x != "")))
    saved_rules.append({"id": rule_id, "field": field, "operator": op, "text": raw})
add_rule = st.button("＋ Добавить фильтр", disabled=len(saved_rules) >= MAX_RULES)
st.info(" И ".join(f"{label(r.field)}: {r.operator.lower()}" + (f" [{'; '.join(r.values)}]" if r.operator not in ("Пусто", "Не пусто") else "") for r in rules))
output_name = st.text_input("Имя результата", settings["output_name"], key="output_name")
replace = st.checkbox("Разрешить замену существующих файлов с теми же именами", key="replace")
keep_raw = st.checkbox(
    "Оставить сырой лог", settings["keep_raw"], key="keep_raw",
    disabled=mode != "Скачать из S3",
    help="Относится только к архивам .tsv.gz, скачанным приложением из S3.",
)
if mode != "Скачать из S3":
    st.caption("Локальный исходный файл никогда не изменяется и не удаляется.")
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

if st.button(
    "Скачать и отфильтровать" if mode == "Скачать из S3" else "Отфильтровать",
    type="primary", disabled=operation_active,
):
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
        if mode == "Скачать из S3":
            archive = Path(folder).expanduser() / f"{selected_date:%Y_%m_%d}_{hour:02d}.tsv.gz"
            if archive.exists() and not replace:
                raise ValueError("Архив уже существует. Выберите «Локальный файл» или разрешите замену")
            operation = partial(
                run_s3_operation, selected_date=selected_date, hour=int(hour), folder=folder,
                endpoint=endpoint, bucket=bucket, prefix=prefix, profile=profile,
                proxy=proxy, archive=archive, destination=destination,
                rules=tuple(rules), keep_raw=keep_raw,
            )
        else:
            if not local_path.strip(): raise ValueError("Укажите путь к логу")
            source = Path(local_path).expanduser()
            operation = partial(
                run_local_operation, source=source, destination=destination,
                rules=tuple(rules),
            )
        st.session_state.operation_archive = str(archive.resolve()) if archive else None
        if controller.start(operation):
            st.rerun()
    except Exception as error:
        st.error(f"Операция не завершена ({type(error).__name__}): {error}")
        st.caption("Проверьте путь, AWS-профиль и доступ к S3. Временные .part удаляются, а итоговый файл заменяется только после успешной обработки.")


def format_bytes(value):
    if value >= 1024 ** 2:
        return f"{value / 1024 ** 2:.1f} МБ"
    return f"{value / 1024:.1f} КБ"


def format_speed(value):
    return f"{format_bytes(value)}/с"


poll_operation = operation_active


@st.fragment(run_every=0.5 if poll_operation else None)
def render_operation():
    snapshot = controller.snapshot()
    if poll_operation and not snapshot.active:
        st.rerun(scope="app")

    if not snapshot.active:
        st.session_state.cancel_confirmation = False

    if snapshot.active:
        if st.session_state.get("cancel_confirmation", False):
            st.warning("Подтвердите отмену. Будут удалены только временные файлы и файлы, созданные текущей операцией.")
            confirm, back = st.columns(2)
            if confirm.button("Подтвердить отмену", type="primary", key="cancel_confirm"):
                controller.cancel()
                st.session_state.cancel_confirmation = False
                st.rerun(scope="app")
            if back.button("Вернуться", key="cancel_back"):
                st.session_state.cancel_confirmation = False
                st.rerun(scope="app")
        else:
            controls = st.columns(2)
            if snapshot.status in ("downloading", "pausing", "paused"):
                pause_label = "Продолжить" if snapshot.status in ("pausing", "paused") else "Пауза"
                if controls[0].button(pause_label, key="pause_resume"):
                    if snapshot.status in ("pausing", "paused"):
                        controller.resume()
                    else:
                        controller.pause()
                    st.rerun(scope="app")
            if controls[1].button("Отменить", key="cancel_request"):
                st.session_state.cancel_confirmation = True
                st.rerun(scope="app")

    if snapshot.status == "preparing":
        st.info("Состояние: подготовка…")
    elif snapshot.status in ("downloading", "pausing", "paused"):
        status_text = {
            "downloading": "Состояние: скачивание",
            "pausing": "Состояние: завершается текущая порция перед паузой…",
            "paused": "Состояние: пауза",
        }[snapshot.status]
        st.info(status_text)
        if snapshot.percent is None:
            st.progress(0.0, text=f"Получено {format_bytes(snapshot.downloaded_bytes)} · общий размер неизвестен")
        else:
            st.progress(
                snapshot.percent / 100.0,
                text=(f"Получено {format_bytes(snapshot.downloaded_bytes)} из "
                      f"{format_bytes(snapshot.total_bytes)} · {snapshot.percent:.1f}%"),
            )
        st.caption(f"Текущая скорость: {format_speed(snapshot.speed_bytes_per_second)}")
    elif snapshot.status == "filtering":
        st.info("Состояние: фильтрация")
        if snapshot.total_bytes is not None:
            st.progress(
                1.0,
                text=(f"Скачивание завершено: {format_bytes(snapshot.downloaded_bytes)} из "
                      f"{format_bytes(snapshot.total_bytes)} · 100%"),
            )
        else:
            st.caption(f"Скачивание завершено: получено {format_bytes(snapshot.downloaded_bytes)}")
        if snapshot.downloaded_bytes:
            st.caption(f"Средняя скорость скачивания: {format_speed(snapshot.speed_bytes_per_second)}")
        st.caption(f"Обработано строк: {snapshot.checked:,} · найдено: {snapshot.matched:,}")
    elif snapshot.status == "cancelling":
        st.info("Состояние: отмена… Ожидается безопасная остановка и очистка файлов.")
    elif snapshot.status == "cancelled":
        st.info("Состояние: операция отменена. Можно начать новую.")
    elif snapshot.status == "failed":
        st.error(f"Состояние: ошибка. Операция не завершена ({snapshot.error})")
        archive_path = st.session_state.get("operation_archive")
        if archive_path and Path(archive_path).exists():
            st.warning(f"Архив оставлен для диагностики или повторной обработки: {archive_path}")
        st.caption("Проверьте путь, AWS-профиль и доступ к S3. Временные .part удаляются, а итоговый файл заменяется только после успешной обработки.")
    elif snapshot.status == "completed":
        payload = snapshot.result
        result = payload["filter_result"]
        st.success(f"Состояние: готово. Результат: {payload['path']}")
        st.caption(payload["archive_note"])
        if snapshot.downloaded_bytes:
            st.caption(f"Средняя скорость скачивания: {format_speed(snapshot.speed_bytes_per_second)}")
        a, b, c = st.columns(3)
        a.metric("Обработано строк", result["checked"])
        b.metric("Найдено", result["matched"])
        c.metric("Некорректных строк", result["malformed"])
        if result["preview"]:
            st.caption("Первые 50 найденных строк. Полный результат сохранён на диске.")
            st.dataframe(result["preview"])
        else:
            st.info("Совпадений нет. Сохранён файл с заголовком.")


render_operation()
