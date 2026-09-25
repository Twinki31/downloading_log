"""Русские подписи для служебных элементов интерфейса Streamlit."""

import json

import streamlit as st
import streamlit.components.v1 as legacy_components


# Streamlit пока не предоставляет настройку языка для своего верхнего меню.
# Словарь ограничен служебной оболочкой и не затрагивает текст самого приложения.
TRANSLATIONS = {
    "Deploy": "Опубликовать",
    "System": "Системная",
    "Light": "Светлая",
    "Dark": "Тёмная",
    "Rerun": "Перезапустить",
    "File change.": "Файл изменён.",
    "Always rerun": "Всегда перезапускать",
    "Auto rerun": "Автоперезапуск",
    "Stop": "Остановить",
    "Stopping...": "Остановка…",
    "Running...": "Выполняется…",
    "Connecting": "Подключение",
    "Connecting to Streamlit server": "Подключение к серверу Streamlit",
    "Connecting to static app": "Подключение к приложению",
    "Error": "Ошибка",
    "Unable to connect to Streamlit server": "Не удалось подключиться к серверу Streamlit",
    "Clear cache": "Очистить кэш",
    "Print": "Печать",
    "Record screen": "Записать экран",
    "Cancel recording": "Отменить запись",
    "Stop recording": "Остановить запись",
    "Main menu": "Главное меню",
    "Copy version to clipboard": "Скопировать версию",
    "Copied": "Скопировано",
    "Record a screencast": "Запись экрана",
    "This will record a video with the contents of your screen, so you can easily share what you're seeing with others.":
        "Будет записано видео с содержимым экрана, которым можно поделиться с другими.",
    "Also record audio": "Также записывать звук",
    "Press `Esc` any time to stop recording.": "Чтобы остановить запись, нажмите `Esc`.",
    "Start recording!": "Начать запись",
    "Due to limitations with some browsers, this feature is only supported on recent desktop versions of Chrome, Firefox, and Edge.":
        "Из-за ограничений браузеров запись поддерживается только в новых настольных версиях Chrome, Firefox и Edge.",
    "Alien Monster": "Инопланетный монстр",
    "Next steps": "Следующие шаги",
    "Step 1": "Шаг 1",
    "Preview your video below:": "Просмотрите записанное видео:",
    "Step 2": "Шаг 2",
    "Save video to disk": "Сохранить видео на диск",
    "About": "О приложении",
    "Report a bug": "Сообщить об ошибке",
    "Get help": "Получить помощь",
}

PREFIX_TRANSLATIONS = {
    "Made with Streamlit v": "Создано с помощью Streamlit v",
}

ELEMENT_TRANSLATIONS = {
    "[data-testid='stScreencastInstruction']": "Чтобы остановить запись, нажмите Esc.",
}


def localization_html() -> str:
    """Возвращает небольшой скрипт, переводящий оболочку родительской страницы."""
    translations = json.dumps(TRANSLATIONS, ensure_ascii=False).replace("</", "<\\/")
    prefix_translations = json.dumps(PREFIX_TRANSLATIONS, ensure_ascii=False).replace("</", "<\\/")
    element_translations = json.dumps(ELEMENT_TRANSLATIONS, ensure_ascii=False).replace("</", "<\\/")
    return f"""
    <script>
    (() => {{
        const doc = window.parent.document;
        const translations = {translations};
        const prefixTranslations = {prefix_translations};
        const elementTranslations = {element_translations};

        function translated(value) {{
            if (translations[value]) return translations[value];
            for (const [prefix, replacement] of Object.entries(prefixTranslations)) {{
                if (value.startsWith(prefix)) return replacement + value.slice(prefix.length);
            }}
            return value;
        }}

        function translateText(node) {{
            if (!node.nodeValue || node.parentElement?.matches("script, style")) return;
            const value = node.nodeValue;
            const trimmed = value.trim();
            const replacement = translated(trimmed);
            if (replacement !== trimmed) {{
                node.nodeValue = value.replace(trimmed, replacement);
            }}
        }}

        function translateElement(element) {{
            for (const [selector, replacement] of Object.entries(elementTranslations)) {{
                if (element.matches?.(selector) && element.textContent !== replacement) {{
                    element.textContent = replacement;
                }}
            }}
            for (const attribute of ["aria-label", "title"]) {{
                if (element.hasAttribute?.(attribute)) {{
                    const value = element.getAttribute(attribute);
                    const replacement = translated(value);
                    if (replacement !== value) element.setAttribute(attribute, replacement);
                }}
            }}
        }}

        function translateTree(root) {{
            if (root.nodeType === Node.TEXT_NODE) translateText(root);
            if (root.nodeType === Node.ELEMENT_NODE) translateElement(root);
            const walker = doc.createTreeWalker(
                root,
                NodeFilter.SHOW_ELEMENT | NodeFilter.SHOW_TEXT,
            );
            let node;
            while ((node = walker.nextNode())) {{
                if (node.nodeType === Node.TEXT_NODE) translateText(node);
                else translateElement(node);
            }}
        }}

        translateTree(doc.documentElement);
        new MutationObserver((mutations) => {{
            for (const mutation of mutations) {{
                if (mutation.type === "characterData") translateText(mutation.target);
                else if (mutation.type === "attributes") translateElement(mutation.target);
                else for (const node of mutation.addedNodes) translateTree(node);
            }}
        }}).observe(doc.documentElement, {{
            subtree: true,
            childList: true,
            characterData: true,
            attributes: true,
            attributeFilter: ["aria-label", "title"],
        }});
    }})();
    </script>
    """


def install_streamlit_localization() -> None:
    """Устанавливает перевод, не добавляя видимую область на страницу."""
    html = localization_html()
    if hasattr(st, "iframe"):
        st.iframe(html, height="content", width="content")
    else:  # Совместимость с поддерживаемыми версиями Streamlit до появления st.iframe.
        legacy_components.html(html, height=0, width=0)
