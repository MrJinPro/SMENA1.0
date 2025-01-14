import os
import configparser
from datetime import datetime
from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QTableWidget, QTableWidgetItem, QHeaderView,
    QToolButton, QMenu, QAction, QPushButton, QMessageBox, QLabel, QHBoxLayout, QApplication
)
from PyQt5.QtCore import Qt, QTimer, QEventLoop
from PyQt5.QtGui import QIcon
import logging

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger('alarm_details_dialog')

current_dir = os.path.dirname(os.path.abspath(__file__))
dark_theme_path = os.path.join(current_dir, '..', 'assets', 'styles', 'dark_theme.qss')
light_theme_path = os.path.join(current_dir, '..', 'assets', 'styles', 'light_theme.qss')

def resource_path(relative_path, project_root):
    """Возвращает абсолютный путь к ресурсу."""
    return os.path.join(project_root, relative_path)

# Словарь для отображения state_event -> текст (при желании).
STATE_NAME_MAP = {
    0:  "Активная тревога",    
    1:  "Принят в обработку",
    2:  "Выслана группа реагирования",
    3:  "Прибытие группы реагирования",
    4:  "Окончание обработки",
    5:  "Перехват события",
    6:  "Объект переведен в стенды",
    7:  "Отмена вызова группы реагирования",
    8:  "Отмена тревоги",
    9:  "Патруль",
    10: "Включение зажигания",
    11: "Выключение зажигания",
    12: "Перезапуск Орлан-GPRS",
    13: "Обработка нового дополнительного события",
    14: "Оповещение ответственных лиц",
    15: "Пересылка по Contact-ID",
}

class AlarmDetailsDialog(QDialog):
    """Диалоговое окно для отображения подробностей тревоги и ответственных лиц."""

    def __init__(self, alarms_info, responsibles=None, parent=None):
        super().__init__(parent)

        # В parent (MainWindow) может быть свойство project_root и current_theme.
        self.project_root = getattr(parent, 'project_root', os.path.dirname(os.path.abspath(__file__)))
        self.current_theme = getattr(parent, 'current_theme', 'Темная')

        self.setWindowTitle("Подробности тревоги")
        self.setGeometry(200, 200, 1300, 600)
        self.setObjectName("dialog")  # Для QSS

        # Применяем стили
        self.apply_styles()

        # Инициализация интерфейса
        self.init_ui(alarms_info, responsibles)

    def init_ui(self, alarms_info, responsibles):
        """Инициализирует пользовательский интерфейс диалога."""
        self.main_layout = QVBoxLayout(self)
        self.setLayout(self.main_layout)

        # Заголовок
        header_label = QLabel("Информация о тревоге")
        header_label.setObjectName("header-label")
        self.main_layout.addWidget(header_label)

        # Удаляем дубликаты тревог (по event_id)
        unique_alarms = self.remove_duplicate_alarms(alarms_info)

        # Создаем таблицу для отображения информации о тревогах
        self.create_alarms_table(unique_alarms)
        self.main_layout.addWidget(self.alarms_table)

        # Добавляем селектор столбцов
        self.create_column_selector(self.main_layout)

        # Заголовок для ответственных лиц
        responsibles_label = QLabel("Ответственные лица")
        responsibles_label.setObjectName("header-label")
        self.main_layout.addWidget(responsibles_label)

        # Создаем таблицу для отображения ответственных лиц
        self.create_responsibles_table(responsibles)
        self.main_layout.addWidget(self.responsibles_table)

        # Кнопка «Закрыть»
        close_button = QPushButton("Закрыть")
        close_button.clicked.connect(self.close)
        self.main_layout.addWidget(close_button)

        # Загружаем сохраненные настройки столбцов
        self.load_default_columns()

    def apply_styles(self):
        """Применяет стили из файла в зависимости от темы"""
        theme_path = dark_theme_path if self.current_theme == "Темная" else light_theme_path
        if os.path.exists(theme_path):
            try:
                with open(theme_path, "r", encoding='utf-8') as f:
                    style = f.read()
                self.setStyleSheet(style)
            except Exception as e:
                logger.info(f"Ошибка при применении стиля '{self.current_theme}': {e}")
        else:
            logger.info(f"Файл стилей не найден по пути: {theme_path}")

    def remove_duplicate_alarms(self, alarms_info):
        """
        Удаляет дубликаты тревог по event_id.
        """
        seen_event_ids = set()
        unique_alarms = []
        for alarm in alarms_info:
            evt_id = alarm.get('event_id')
            if evt_id not in seen_event_ids:
                unique_alarms.append(alarm)
                seen_event_ids.add(evt_id)
        return unique_alarms

    def create_alarms_table(self, alarms):
        """
        Создает таблицу для отображения информации о тревогах.
        Предполагаем, что поле:
          - panel_id
          - code
          - time_event
          - state_event
          - event_id
        """
        from PyQt5.QtWidgets import QTableWidget  # Локальный импорт, если нужно
        self.alarms_table = QTableWidget()
        self.alarms_table.setRowCount(len(alarms))
        self.alarms_table.setColumnCount(5)
        self.alarms_table.setHorizontalHeaderLabels([
            "Объект", "Код события", "Время события", "Состояние события", "ID события"
        ])
        self.alarms_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.alarms_table.setObjectName("alarms-table")

        for row, alarm_info in enumerate(alarms):
            panel_id = alarm_info.get('panel_id', "Нет panel_id")
            code_val = alarm_info.get('code', "Нет кода")
            t_evt = alarm_info.get('time_event')
            if isinstance(t_evt, datetime):
                time_str = t_evt.strftime('%Y-%m-%d %H:%M:%S')
            elif t_evt is None:
                time_str = "Нет времени"
            else:
                time_str = str(t_evt)

            state_val = alarm_info.get('state_event')
            if isinstance(state_val, int):
                # берем из словаря или пишем «StateEvent=…»
                state_str = STATE_NAME_MAP.get(state_val, f"StateEvent={state_val}")
            else:
                state_str = "Неизвестно"

            evt_id = alarm_info.get('event_id', 'Нет event_id')

            values = [str(panel_id), str(code_val), time_str, state_str, str(evt_id)]
            for col, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setTextAlignment(Qt.AlignCenter)
                self.alarms_table.setItem(row, col, item)

        self.alarms_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.alarms_table.setEditTriggers(QTableWidget.NoEditTriggers)

    def create_responsibles_table(self, responsibles):
        """Создает таблицу для отображения ответственных лиц."""
        from PyQt5.QtWidgets import QTableWidget
        self.responsibles_table = QTableWidget()
        self.responsibles_table.setColumnCount(5)
        self.responsibles_table.setHorizontalHeaderLabels(["№", "Имя", "Телефон", "Адрес", "Действие"])
        self.responsibles_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.responsibles_table.setObjectName("responsibles-table")

        if responsibles:
            self.load_responsibles(responsibles)
        else:
            self.responsibles_table.setRowCount(1)
            self.responsibles_table.setItem(0, 0, QTableWidgetItem("Нет данных о ответственных лицах"))
            for col in range(1, 5):
                self.responsibles_table.setItem(0, col, QTableWidgetItem(""))

        self.responsibles_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.responsibles_table.setEditTriggers(QTableWidget.NoEditTriggers)

    def create_column_selector(self, layout):
        """Создает кнопку для выбора отображаемых столбцов."""
        selector_layout = QHBoxLayout()
        selector_layout.addStretch()

        self.column_selector_button = QToolButton()
        self.column_selector_button.setText("Выбрать столбцы")
        self.column_selector_button.setPopupMode(QToolButton.InstantPopup)

        icon_path = resource_path(os.path.join('..', 'resources', 'icons', 'settings_icon.png'), self.project_root)
        if os.path.exists(icon_path):
            self.column_selector_button.setIcon(QIcon(icon_path))

        menu = QMenu(self)

        self.checkboxes = []
        for i in range(self.alarms_table.columnCount()):
            hdr_text = self.alarms_table.horizontalHeaderItem(i).text()
            action = QAction(hdr_text, self)
            action.setCheckable(True)
            action.setChecked(True)
            action.triggered.connect(self.update_columns)
            self.checkboxes.append(action)
            menu.addAction(action)

        save_action = QAction("Сохранить по умолчанию", self)
        save_action.triggered.connect(self.save_default_columns)
        menu.addAction(save_action)

        self.column_selector_button.setMenu(menu)
        selector_layout.addWidget(self.column_selector_button)

        layout.addLayout(selector_layout)

        # Задержка скрытия
        menu.aboutToHide.connect(self.delay_hide_menu)

    def update_columns(self):
        """Показываем/скрываем столбцы в таблице тревог."""
        for i, action in enumerate(self.checkboxes):
            self.alarms_table.setColumnHidden(i, not action.isChecked())

    def save_default_columns(self):
        """Сохраняет выбранные столбцы для таблицы тревог."""
        config = configparser.ConfigParser()
        config_path = resource_path('config.ini', self.project_root)
        config.read(config_path, encoding='utf-8')

        if not config.has_section('AlarmDetails'):
            config.add_section('AlarmDetails')

        selected_columns = [str(i) for i, action in enumerate(self.checkboxes) if action.isChecked()]
        config.set('AlarmDetails', 'columns', ','.join(selected_columns))

        with open(config_path, 'w', encoding='utf-8') as configfile:
            config.write(configfile)

    def load_default_columns(self):
        """Загружаем сохраненные колонки."""
        config = configparser.ConfigParser()
        config_path = resource_path('config.ini', self.project_root)
        config.read(config_path, encoding='utf-8')

        if config.has_option('AlarmDetails', 'columns'):
            selected_columns = config.get('AlarmDetails', 'columns').split(',')
            for i, action in enumerate(self.checkboxes):
                action.setChecked(str(i) in selected_columns)
            self.update_columns()

    def load_responsibles(self, responsibles):
        """Наполняет таблицу ответственными лицами."""
        from PyQt5.QtWidgets import QTableWidgetItem
        unique_phones = set()
        valid_responsibles = []

        for responsible in responsibles:
            phone = responsible.get('phone', 'Неизвестно')
            # Проверим длину номера (11+ для РФ, например)
            if len(phone) >= 6 and phone not in unique_phones:
                unique_phones.add(phone)
                valid_responsibles.append(responsible)

        self.responsibles_table.setRowCount(len(valid_responsibles))

        for idx, responsible in enumerate(valid_responsibles, start=1):
            name = responsible.get('name', 'Неизвестно')
            phone = responsible.get('phone', 'Неизвестно')
            address = responsible.get('address', 'Неизвестно')

            self.responsibles_table.setItem(idx - 1, 0, QTableWidgetItem(str(idx)))
            self.responsibles_table.setItem(idx - 1, 1, QTableWidgetItem(name))
            self.responsibles_table.setItem(idx - 1, 2, QTableWidgetItem(phone))
            self.responsibles_table.setItem(idx - 1, 3, QTableWidgetItem(address))

            call_button = QPushButton("Позвонить")
            call_button.setObjectName("call-button")
            call_button.clicked.connect(lambda _, p=phone: self.make_call(p))
            self.responsibles_table.setCellWidget(idx - 1, 4, call_button)

    def make_call(self, phone_number):
        QMessageBox.information(self, "Звонок", f"Имитируем звонок на номер: {phone_number}")

    def delay_hide_menu(self):
        QTimer.singleShot(300, lambda: QApplication.processEvents(QEventLoop.AllEvents, 300))
