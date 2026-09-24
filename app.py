"""Интерфейс приложения. Запуск: python -m streamlit run app.py"""
from datetime import date
from pathlib import Path
import json
import streamlit as st
from fields import FIELDS, label
from filtering import OPERATORS, Rule, filter_log
from download import download_log

st.set_page_config(page_title="Логи AdFox", page_icon="📄", layout="wide")
st.title("Логи AdFox")
st.caption("Скачивание и фильтрация на вашем компьютере")

DEFAULTS = {
    "endpoint": "https://s3-private.mds.yandex.net",
    "bucket": "adfox-unload-imho-video", "prefix": "imho-video",
    "profile": "", "proxy": False,
    "folder": str(Path.home() / "Downloads" / "adfox_logs"),
    "rules": [{"field": "banner_id", "operator": "Одно из значений", "text": "208684"},
              {"field": "flag_virtual", "operator": "Одно из значений", "text": "0"}],
}
if "settings" not in st.session_state:
    st.session_state.settings = DEFAULTS.copy()
    st.session_state.rule_count = len(DEFAULTS["rules"])
settings = st.session_state.settings
with st.sidebar:
    st.header("Настройки")
    uploaded = st.file_uploader("Загрузить настройки JSON", type="json")
    if st.button("Применить настройки", disabled=uploaded is None):
        try:
            data = json.load(uploaded)
            merged = DEFAULTS | data
            if not isinstance(data, dict) or not isinstance(merged["rules"], list) or not 1 <= len(merged["rules"]) <= 30:
                raise ValueError("Нужны от 1 до 30 фильтров")
            for key in ("endpoint", "bucket", "prefix", "profile", "folder"):
                if not isinstance(merged[key], str): raise ValueError("Некорректные настройки")
            if not isinstance(merged["proxy"], bool): raise ValueError("Некорректная настройка proxy")
            for r in merged["rules"]:
                if r["field"] not in FIELDS or r["operator"] not in OPERATORS or not isinstance(r["text"], str):
                    raise ValueError("Некорректный фильтр")
            for key in list(st.session_state):
                if key.startswith("rule_") or key in ("endpoint", "bucket", "prefix", "profile", "proxy", "folder"):
                    del st.session_state[key]
            st.session_state.settings = merged
            st.session_state.rule_count = len(merged["rules"])
            st.rerun()
        except (ValueError, TypeError, KeyError):
            st.error("Не удалось прочитать настройки. Проверьте JSON и поля фильтров.")
    folder = st.text_input("Папка результатов", settings["folder"], key="folder")
    with st.expander("Подключение к S3"):
        endpoint = st.text_input("Адрес S3", settings["endpoint"], key="endpoint")
        bucket = st.text_input("Bucket", settings["bucket"], key="bucket")
        prefix = st.text_input("Папка в bucket", settings["prefix"], key="prefix")
        profile = st.text_input("AWS-профиль (пусто — стандартный)", settings["profile"], key="profile")
        proxy = st.checkbox("Использовать proxy из окружения", settings["proxy"], key="proxy")
    st.caption("Используется существующий AWS-профиль. Ключи доступа в настройки приложения не записываются.")

mode = st.radio("Источник", ["Скачать из S3", "Локальный файл"], horizontal=True)
if mode == "Скачать из S3":
    left, right = st.columns(2)
    selected_date = left.date_input("Дата в имени файла", date.today())
    hour = right.number_input("Час в имени файла", 0, 23, 12)
    st.caption("Дата и час используются как есть, без преобразования часового пояса.")
else:
    local_path = st.text_input("Полный путь к файлу .tsv.gz или .tsv")

st.subheader("Фильтры")
st.caption("Все строки условий должны выполняться одновременно (И). Значения внутри одного фильтра — ИЛИ. Регистр учитывается.")
rules, saved_rules = [], []
for i in range(st.session_state.rule_count):
    default = settings["rules"][i] if i < len(settings["rules"]) else {"field": "useragent", "operator": "Содержит", "text": ""}
    a, b, c = st.columns([2, 2, 3])
    field = a.selectbox(f"Поле {i+1}", FIELDS, index=FIELDS.index(default["field"]), format_func=label, key=f"rule_field_{i}")
    op = b.selectbox(f"Условие {i+1}", OPERATORS, index=OPERATORS.index(default["operator"]), key=f"rule_op_{i}")
    raw = c.text_area(f"Значения {i+1} — каждое с новой строки", default["text"], height=90, key=f"rule_text_{i}", disabled=op in ("Пусто", "Не пусто"))
    rules.append(Rule(field, op, tuple(x for x in raw.splitlines() if x != "")))
    saved_rules.append({"field": field, "operator": op, "text": raw})
a, b = st.columns(2)
if a.button("＋ Добавить фильтр", disabled=st.session_state.rule_count >= 30):
    st.session_state.rule_count += 1
    st.rerun()
if b.button("Удалить последний фильтр", disabled=st.session_state.rule_count <= 1):
    st.session_state.rule_count -= 1
    st.rerun()
st.info(" И ".join(f"{label(r.field)}: {r.operator.lower()}" + (f" [{'; '.join(r.values)}]" if r.operator not in ("Пусто", "Не пусто") else "") for r in rules))
st.caption("flag_virtual = 0 перенесён из исходного скрипта и теперь виден как обычный редактируемый фильтр. Неизвестные поля оставлены без выдуманных расшифровок.")
output_name = st.text_input("Имя результата", "filtered.tsv")
replace = st.checkbox("Разрешить замену существующих файлов с теми же именами")
export = dict(endpoint=endpoint, bucket=bucket, prefix=prefix, profile=profile, proxy=proxy, folder=folder, rules=saved_rules)
st.download_button("Сохранить настройки", json.dumps(export, ensure_ascii=False, indent=2), "adfox_settings.json", "application/json")

if st.button("Скачать и отфильтровать" if mode == "Скачать из S3" else "Отфильтровать", type="primary"):
    st.session_state.pop("result", None)
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
            source = download_log(selected_date, hour, folder, endpoint, bucket, prefix, profile, proxy, downloaded)
        else:
            if not local_path.strip(): raise ValueError("Укажите путь к логу")
            source = Path(local_path).expanduser()
        status.info("Фильтрация…")
        result = filter_log(source, destination, rules, lambda n, m: status.info(f"Обработано: {n:,}. Найдено: {m:,}"))
        status.empty()
        st.session_state.result = (str(destination.resolve()), result)
    except Exception as error:
        st.error(f"Операция не завершена ({type(error).__name__}): {error}")
        st.caption("Проверьте путь, AWS-профиль и доступ к S3. Итоговый файл заменяется только после успешной обработки.")
if "result" in st.session_state:
    path, result = st.session_state.result
    st.success(f"Готово: {path}")
    a, b, c = st.columns(3)
    a.metric("Обработано строк", result["checked"])
    b.metric("Найдено", result["matched"])
    c.metric("Некорректных строк", result["malformed"])
    if result["preview"]:
        st.caption("Первые 50 найденных строк. Полный результат сохранён на диске.")
        st.dataframe(result["preview"])
    else:
        st.info("Совпадений нет. Сохранён файл с заголовком.")
