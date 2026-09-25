"""Отдельная справочная страница со всеми описаниями полей."""
import streamlit as st

from fields import FIELDS, description


st.set_page_config(page_title="Описание полей · Логи AdFox", page_icon="📖", layout="wide")
st.title("Описание полей")
st.caption("Полные пояснения ко всем полям логов.")
st.markdown("[← Вернуться к фильтрам](/)")

rows = []
for field in FIELDS:
    if field == "oc1":
        rows.append({"Поле": "oc1–oc63", "Описание": description(field)})
    elif field.startswith("oc") and field[2:].isdigit() and 1 <= int(field[2:]) <= 63:
        continue
    else:
        rows.append({"Поле": field, "Описание": description(field)})

st.table(rows)
