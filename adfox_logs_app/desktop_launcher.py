"""Запуск локального Streamlit-интерфейса из настольного приложения."""

from pathlib import Path
import sys
import threading
import time
from urllib.request import urlopen
import webbrowser


APP_URL = "http://127.0.0.1:8501"


def bundled_path(relative_path):
    """Найти файл рядом с исходниками или во временной папке PyInstaller."""
    root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    return root / relative_path


def streamlit_arguments(app_path):
    """Параметры безопасного локального запуска без внешнего сетевого доступа."""
    return [
        "streamlit", "run", str(app_path),
        "--server.address=127.0.0.1",
        "--server.port=8501",
        "--server.headless=false",
        "--server.maxUploadSize=1",
        "--browser.gatherUsageStats=false",
        "--client.showSidebarNavigation=false",
        "--logger.hideWelcomeMessage=true",
        "--global.developmentMode=false",
    ]


def server_is_ready():
    """Проверить штатную health-страницу локального Streamlit."""
    try:
        with urlopen(f"{APP_URL}/_stcore/health", timeout=0.5) as response:
            return response.read().strip() == b"ok"
    except OSError:
        return False


def open_browser_when_ready(*, ready=server_is_ready, opener=webbrowser.open,
                            attempts=120, delay=0.25):
    """Открыть браузер после запуска сервера или закончить ожидание по таймауту."""
    for _ in range(attempts):
        if ready():
            opener(APP_URL)
            return True
        time.sleep(delay)
    return False


def main():
    app_path = bundled_path("app.py")
    if not app_path.is_file():
        raise FileNotFoundError(f"Не найден файл приложения: {app_path}")

    # Импорт после проверки пути ускоряет простые тесты launcher-функций.
    from streamlit.web import cli as streamlit_cli

    threading.Thread(target=open_browser_when_ready, daemon=True).start()
    sys.argv = streamlit_arguments(app_path)
    raise SystemExit(streamlit_cli.main())


if __name__ == "__main__":
    main()
