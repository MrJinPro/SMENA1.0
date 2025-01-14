import sys
import os
import configparser
import logging
from logging.handlers import RotatingFileHandler
from PyQt5.QtWidgets import QApplication
from PyQt5.QtGui import QIcon
from ui.main_window import MainWindow

# Функция для получения пути к ресурсам
def resource_path(relative_path):
    """Получение абсолютного пути к ресурсам, работает как в режиме разработки, так и после сборки."""
    try:
        # PyInstaller создаёт временную папку и сохраняет пути к ресурсам в _MEIPASS
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")

    return os.path.join(base_path, relative_path)

# Настройка логирования
def setup_logging():
    project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
    log_dir = os.path.join(project_root, 'logs')
    if not os.path.exists(log_dir):
        os.makedirs(log_dir)
    log_file = os.path.join(log_dir, 'smena.log')

    # Создаём ротационный обработчик (максимальный размер файла 5 МБ, 5 резервных копий)
    handler = RotatingFileHandler(log_file, maxBytes=5*1024*1024, backupCount=5, encoding='utf-8')
    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    handler.setFormatter(formatter)

    # Получаем корневой логгер и настраиваем его
    logger = logging.getLogger()
    logger.setLevel(logging.DEBUG)  # Уровень логирования можно настроить по необходимости

    # Добавляем обработчики
    logger.addHandler(handler)

    # Добавляем обработчик для вывода в консоль (опционально)
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

# Используем абсолютный путь для всех операций с конфигурацией и иконками
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
icon_256_path = os.path.join(project_root, 'resources', 'icons', 'Smena-256.ico')

# Загрузка конфигурации один раз
config_path = os.path.join(os.path.dirname(__file__), 'ui', 'config.ini')
config = configparser.ConfigParser()
config.read(config_path, encoding='utf-8')

def main():
    setup_logging()
    logger = logging.getLogger(__name__)
    logger.info("Запуск приложения Smena.")

    # Инициализация основного GUI приложения
    app = QApplication(sys.argv)

    # Устанавливаем иконку для всего приложения (панель задач)
    app.setWindowIcon(QIcon(resource_path('resources/icons/Smena-256.ico')))

    # Передаём объект конфигурации в главное окно
    main_window = MainWindow(config)
    main_window.show()

    # Запуск главного цикла приложения
    try:
        sys.exit(app.exec_())
    except Exception as e:
        logger.exception("Произошла непредвиденная ошибка:")

if __name__ == "__main__":
    main()
    
