# smena.py
import sys
import os
import configparser
import logging
from logging.handlers import RotatingFileHandler
from PyQt5.QtWidgets import QApplication
from PyQt5.QtGui import QIcon

from ui.main_window import MainWindow

def resource_path(relative_path):
    """
    Получение абсолютного пути к ресурсам, работает как в режиме разработки,
    так и после сборки.
    """
    try:
        # PyInstaller создаёт временную папку и сохраняет пути к ресурсам в _MEIPASS
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")

    return os.path.join(base_path, relative_path)


def setup_logging():
    """
    Настройка логирования, все логи складываются в logs/smena.log.
    """
    # Определяем путь к папке logs рядом с текущим .py файлом.
    script_dir = os.path.dirname(os.path.abspath(__file__))
    log_dir = os.path.join(script_dir, 'logs')
    if not os.path.exists(log_dir):
        os.makedirs(log_dir)

    log_file = os.path.join(log_dir, 'smena.log')

    # Ротационный обработчик: 5 МБ макс, 5 бэкапов
    handler = RotatingFileHandler(log_file, maxBytes=5 * 1024 * 1024, backupCount=5, encoding='utf-8')
    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    handler.setFormatter(formatter)

    logger = logging.getLogger()
    logger.setLevel(logging.DEBUG)
    logger.addHandler(handler)

    # При желании добавить вывод в консоль:
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)


def main():
    setup_logging()
    logger = logging.getLogger(__name__)
    logger.info("Запуск приложения Smena.")

    # Загружаем конфигурацию
    script_dir = os.path.dirname(os.path.abspath(__file__))
    config_path = os.path.join(script_dir, 'ui', 'config.ini')
    config = configparser.ConfigParser()
    config.read(config_path, encoding='utf-8')

    from PyQt5.QtWidgets import QApplication
    app = QApplication(sys.argv)

    # Устанавливаем иконку приложения
    icon_path = resource_path('resources/icons/Smena-256.ico')
    app.setWindowIcon(QIcon(icon_path))

    main_window = MainWindow(config)
    main_window.show()

    try:
        sys.exit(app.exec_())
    except Exception as e:
        logger.exception("Произошла непредвиденная ошибка:")


if __name__ == "__main__":
    main()
