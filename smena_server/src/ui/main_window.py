import os
import sys
import configparser
import requests
import socket
import logging
import uuid

from PyQt5.QtWidgets import (
    QMainWindow, QHBoxLayout, QVBoxLayout, QWidget, QLabel,
    QScrollArea, QLineEdit, QPushButton, QFormLayout, QMessageBox,
    QAction, QDialog, QFileDialog, QSystemTrayIcon, QMenu
)
from PyQt5.QtCore import (
    Qt, QTimer, QSize, QPropertyAnimation,
    QEasingCurve, QFileSystemWatcher, pyqtSignal
)
from PyQt5.QtGui import (
    QIcon, QPixmap, QFont
)
from datetime import datetime

# Ваши внутренние модули
from db_connector import DBConnector
from ui.monitoring import MonitoringThread
from alarm_handler import AlarmHandler
from ui.alarm_details_dialog import AlarmDetailsDialog
from ui.telephony_settings_dialog import TelephonySettingsDialog
from ui.sms_settings_dialog import SMSSettingsDialog
from ui.call_manager import CallManager
from ui.code_dialog import CodeDialog
from ui.message_dialog import MessageDialog
from ui.event_processor import EventProcessor
from ui.voice_synthesizer_dialog import VoiceSynthesizerSettingsDialog
from ui.event_processing_settings_dialog import EventProcessingSettingsDialog

# Пути к файлам
current_dir = os.path.dirname(os.path.abspath(__file__))
config_path = os.path.abspath(os.path.join(current_dir, 'config.ini'))
icon_16_path = os.path.join(current_dir, '..', 'resources', 'icons', 'Smena-16.ico')
icon_256_path = os.path.join(current_dir, '..', 'resources', 'icons', 'Smena-256.ico')
dark_theme_path = os.path.join(current_dir, '..', 'assets', 'styles', 'dark_theme.qss')
light_theme_path = os.path.join(current_dir, '..', 'assets', 'styles', 'light_theme.qss')

# Иконки меню
menu_icon_path = os.path.join(current_dir, '..', 'resources', 'icons', 'menu_icon.png')
database_icon_path = os.path.join(current_dir, '..', 'resources', 'icons', 'database_icon.png')
telephony_icon_path = os.path.join(current_dir, '..', 'resources', 'icons', 'telephony_icon.png')
sms_icon_path = os.path.join(current_dir, '..', 'resources', 'icons', 'sms_icon.png')
settings_icon_path = os.path.join(current_dir, '..', 'resources', 'icons', 'settings_icon.png')
theme_icon_path = os.path.join(current_dir, '..', 'resources', 'icons', 'theme_icon.png')
exit_icon_path = os.path.join(current_dir, '..', 'resources', 'icons', 'exit_icon.png')
code_icon_path = os.path.join(current_dir, '..', 'resources', 'icons', 'code_icon.png')
message_icon_path = os.path.join(current_dir, '..', 'resources', 'icons', 'message_icon.png')

class EventIDLoggerAdapter(logging.LoggerAdapter):
    """
    Адаптер логирования, добавляющий [EventID: ...] к сообщению.
    """
    def process(self, msg, kwargs):
        extra = kwargs.get('extra', {}).copy()
        if 'event_id' not in extra:
            extra['event_id'] = self.extra.get('event_id', 'N/A')
        kwargs['extra'] = extra
        return msg, kwargs


class MainWindow(QMainWindow):
    def __init__(self, config):
        super().__init__()

        self.config = config
        self.db_connector = None
        self.telephony_manager = None
        self.current_theme = "Темная"  # Тема по умолчанию

        # Настройка логирования
        self.logger = logging.getLogger('ui.event_processor')
        self.logger.setLevel(logging.INFO)
        handler = logging.StreamHandler()
        formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - [EventID: %(event_id)s] - %(message)s'
        )
        handler.setFormatter(formatter)
        self.logger.addHandler(handler)
        self.logger = EventIDLoggerAdapter(self.logger, {'event_id': 'N/A'})

        # Иконка приложения
        self.setWindowIcon(QIcon(icon_256_path))
        self.setWindowTitle("Система Мониторинга - SMENA")
        self.setGeometry(100, 100, 700, 700)

        # Храним список тревог (StateEvent=0 или 1)
        self.alarms_list = []  
        self.displayed_alarms = set()

        # Инициализация интерфейса
        self.init_ui()
        self.apply_styles()

        # Подключение к базе данных
        self.load_and_connect_db()

        # Если не удалось подключиться — открываем окно настроек, но не закрываем программу
        if not self.db_connector or not self.db_connector.connection:
            self.logger.error("Нет подключения к базе данных. Откроем окно настроек БД.")
            self.open_db_settings()

        # Инициализация EventProcessor (только если есть подключение)
        if self.db_connector and self.db_connector.connection:
            self.event_processor = EventProcessor(self.config, self.db_connector, self)
            self.event_processor.alarm_processed.connect(self.remove_alarm_card)
            self.event_processor.start_processing()
        else:
            self.logger.warning("EventProcessor не инициализирован, нет подключения к БД.")

        # Подключение к IP-телефонии и SMS-шлюзу
        self.load_and_connect_telephony()
        self.load_and_connect_sms_gateway()

        # Инициализация мониторинга тревог
        self.monitoring = None
        if self.db_connector and self.db_connector.connection:
            self.monitoring = MonitoringThread(self.db_connector)
            self.monitoring.alarms_found.connect(self.process_alarms)

        # Таймеры
        self.setup_timers()

        # Иконка в системном трее
        self.init_tray_icon()

        # Наблюдатель за стилями
        self.setup_style_watcher()

    # ---------------- UI ----------------
    def init_ui(self):
        """
        Создание основного интерфейса:
         - боковое меню,
         - верхняя панель (статусы),
         - поле поиска,
         - зона тревог.
        """
        self.central_widget = QWidget()
        self.setCentralWidget(self.central_widget)
        self.main_layout = QHBoxLayout(self.central_widget)
        self.main_layout.setContentsMargins(0, 0, 0, 0)
        self.main_layout.setSpacing(0)

        # Боковое меню
        self.create_side_menu()

        # Основная часть
        self.content_widget = QWidget()
        self.content_layout = QVBoxLayout(self.content_widget)
        self.content_layout.setContentsMargins(10, 10, 10, 10)
        self.content_layout.setSpacing(10)

        # Верхняя панель
        self.create_top_bar()

        # Поле поиска
        self.search_line = QLineEdit()
        self.search_line.setPlaceholderText("Поиск по panel_id...")
        self.search_line.textChanged.connect(self.on_search_changed)
        self.content_layout.addWidget(self.search_line)

        # Зона тревог
        self.create_alarm_area()

        self.main_layout.addWidget(self.side_menu_container)
        self.main_layout.addWidget(self.content_widget)

    def create_side_menu(self):
        """Боковое меню со сворачиванием."""
        self.side_menu_container = QWidget()
        self.side_menu_container.setFixedWidth(60)
        self.side_menu_layout = QVBoxLayout(self.side_menu_container)
        self.side_menu_layout.setContentsMargins(0, 0, 0, 0)
        self.side_menu_layout.setSpacing(0)

        self.menu_button = QPushButton()
        self.menu_button.setIcon(QIcon(menu_icon_path))
        self.menu_button.setIconSize(QSize(32, 32))
        self.menu_button.setFixedSize(60, 60)
        self.menu_button.setObjectName("menu-button")
        self.menu_button.clicked.connect(self.toggle_side_menu)
        self.side_menu_layout.addWidget(self.menu_button)

        # Контейнер для остальных кнопок
        self.menu_buttons_widget = QWidget()
        self.menu_buttons_layout = QVBoxLayout(self.menu_buttons_widget)
        self.menu_buttons_layout.setContentsMargins(0, 0, 0, 0)
        self.menu_buttons_layout.setSpacing(0)

        # Кнопки
        self.event_processing_settings_button = self.create_menu_button(
            "Обр... событий",
            settings_icon_path,
            self.open_event_processing_settings
        )
        self.db_settings_button = self.create_menu_button(
            "База данных",
            database_icon_path,
            self.open_db_settings
        )
        self.telephony_settings_button = self.create_menu_button(
            "IP-телефония",
            telephony_icon_path,
            self.open_telephony_settings
        )
        self.sms_settings_button = self.create_menu_button(
            "SMS-шлюз",
            sms_icon_path,
            self.open_sms_settings
        )
        self.voice_synth_settings_button = self.create_menu_button(
            "Синтез речи",
            settings_icon_path,
            self.open_voice_synth_settings
        )
        self.code_settings_button = self.create_menu_button(
            "Коды мониторинга",
            code_icon_path,
            self.open_code_dialog
        )
        self.message_settings_button = self.create_menu_button(
            "Ред сообщение",
            message_icon_path,
            self.open_message_dialog
        )
        self.theme_button = self.create_menu_button(
            "Сменить тему",
            theme_icon_path,
            self.switch_theme
        )

        # Кнопка "О программе"
        self.about_button = self.create_menu_button(
            "О программе",
            message_icon_path,
            self.show_about_dialog
        )

        self.exit_button = self.create_menu_button(
            "Выход",
            exit_icon_path,
            self.close_application
        )

        # Добавляем кнопки
        self.menu_buttons_layout.addWidget(self.event_processing_settings_button)
        self.menu_buttons_layout.addWidget(self.db_settings_button)
        self.menu_buttons_layout.addWidget(self.telephony_settings_button)
        self.menu_buttons_layout.addWidget(self.sms_settings_button)
        self.menu_buttons_layout.addWidget(self.voice_synth_settings_button)
        self.menu_buttons_layout.addWidget(self.code_settings_button)
        self.menu_buttons_layout.addWidget(self.message_settings_button)
        self.menu_buttons_layout.addWidget(self.theme_button)
        self.menu_buttons_layout.addWidget(self.about_button)
        self.menu_buttons_layout.addStretch()
        self.menu_buttons_layout.addWidget(self.exit_button)

        self.side_menu_layout.addWidget(self.menu_buttons_widget)

        self.menu_expanded = False
        self.menu_animation = QPropertyAnimation(self.side_menu_container, b"minimumWidth")
        self.menu_animation.setDuration(300)
        self.menu_animation.setEasingCurve(QEasingCurve.InOutQuart)

    def apply_styles(self):
        """Применяет стили в зависимости от self.current_theme."""
        theme_path = dark_theme_path if self.current_theme == "Темная" else light_theme_path
        try:
            if os.path.exists(theme_path):
                with open(theme_path, "r", encoding='utf-8') as f:
                    style = f.read()
                self.setStyleSheet(style)
                self.logger.info(f"Стиль '{self.current_theme}' применен успешно.")
            else:
                self.logger.error(f"Файл стилей не найден: {theme_path}")
        except Exception as e:
            self.logger.error(f"Ошибка при применении стиля '{self.current_theme}': {e}")

    def switch_theme(self):
        """Переключение между темной и светлой темой."""
        if self.current_theme == "Темная":
            self.current_theme = "Светлая"
        else:
            self.current_theme = "Темная"
        self.apply_styles()
        self.logger.info(f"Тема переключена на {self.current_theme}.")

    def setup_style_watcher(self):
        """Следим за изменениями в файлах стилей."""
        self.style_watcher = QFileSystemWatcher(self)
        self.style_watcher.addPath(dark_theme_path)
        self.style_watcher.addPath(light_theme_path)
        self.style_watcher.fileChanged.connect(self.apply_styles)

    def create_menu_button(self, text, icon_path, callback):
        """Утилита для создания кнопки меню."""
        btn = QPushButton(text)
        btn.setIcon(QIcon(icon_path))
        btn.setIconSize(QSize(24, 24))
        btn.setFixedHeight(50)
        btn.setObjectName("menu-button-item")
        btn.clicked.connect(callback)
        return btn

    def toggle_side_menu(self):
        """Свернуть/развернуть боковое меню с анимацией."""
        if self.menu_expanded:
            # Свернуть
            self.menu_animation.setStartValue(200)
            self.menu_animation.setEndValue(60)
            self.menu_animation.start()
            self.menu_expanded = False
            for b in [
                self.event_processing_settings_button,
                self.db_settings_button,
                self.telephony_settings_button,
                self.sms_settings_button,
                self.voice_synth_settings_button,
                self.code_settings_button,
                self.message_settings_button,
                self.theme_button,
                self.about_button,
                self.exit_button
            ]:
                b.setText("")
        else:
            # Развернуть
            self.menu_animation.setStartValue(60)
            self.menu_animation.setEndValue(200)
            self.menu_animation.start()
            self.menu_expanded = True
            self.event_processing_settings_button.setText("Обр... событий")
            self.db_settings_button.setText("База данных")
            self.telephony_settings_button.setText("IP-телефония")
            self.sms_settings_button.setText("SMS-шлюз")
            self.voice_synth_settings_button.setText("Синтез речи")
            self.code_settings_button.setText("Коды мониторинга")
            self.message_settings_button.setText("Ред сообщение")
            self.theme_button.setText("Сменить тему")
            self.about_button.setText("О программе")
            self.exit_button.setText("Выход")

    def create_top_bar(self):
        """Создаём верхнюю панель (заголовок + статусы)."""
        self.top_bar = QWidget()
        self.top_bar_layout = QHBoxLayout(self.top_bar)
        self.top_bar_layout.setContentsMargins(0, 0, 0, 0)
        self.top_bar_layout.setSpacing(10)

        # Заголовок
        self.app_title = QLabel("SMENA")
        self.app_title.setObjectName("app-title")
        self.top_bar_layout.addWidget(self.app_title)
        self.top_bar_layout.addStretch()

        # Статусы
        self.db_status = self.create_status_widget("База данных", "Отключено", database_icon_path)
        self.telephony_status = self.create_status_widget("IP-телефония", "Отключено", telephony_icon_path)
        self.sms_status = self.create_status_widget("SMS-шлюз", "Отключено", sms_icon_path)

        self.top_bar_layout.addWidget(self.db_status)
        self.top_bar_layout.addWidget(self.telephony_status)
        self.top_bar_layout.addWidget(self.sms_status)

        # Кнопка включения/отключения обработки
        self.processing_toggle_button = QPushButton("Отключить обработку")
        self.processing_toggle_button.setCheckable(True)
        self.processing_toggle_button.setChecked(True)
        self.processing_toggle_button.clicked.connect(self.toggle_event_processing)
        self.top_bar_layout.addWidget(self.processing_toggle_button)

        self.content_layout.addWidget(self.top_bar)

    def create_status_widget(self, name, status, icon_path):
        """
        Возвращает виджет со значком, названием и цветным лейблом статуса.
        """
        w = QWidget()
        layout = QHBoxLayout(w)
        layout.setContentsMargins(5, 0, 5, 0)

        icon_label = QLabel()
        icon_label.setPixmap(QPixmap(icon_path).scaled(24, 24, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        layout.addWidget(icon_label)

        name_label = QLabel(name)
        name_label.setObjectName(f"{name.lower().replace(' ', '_')}-status-name")
        layout.addWidget(name_label)

        status_label = QLabel(status)
        status_label.setObjectName("status_label")
        status_label.setStyleSheet("color: red;")
        layout.addWidget(status_label)

        return w

    def create_alarm_area(self):
        """Зона отображения тревожных карточек."""
        self.alarm_area = QScrollArea()
        self.alarm_area.setWidgetResizable(True)

        self.alarm_container = QWidget()
        self.alarm_layout = QVBoxLayout(self.alarm_container)
        self.alarm_layout.setContentsMargins(0, 0, 0, 0)
        self.alarm_layout.setSpacing(10)

        self.alarm_area.setWidget(self.alarm_container)
        self.content_layout.addWidget(self.alarm_area)

    # ----------------- Поиск и перерисовка -----------------
    def on_search_changed(self, text: str):
        """Перерисовываем карточки при изменении текста поиска."""
        self.update_alarm_cards()

    def update_alarm_cards(self):
        """Удаляем все карточки и пересоздаем по self.alarms_list (StateEvent=0,1) + фильтр поиска."""
        while self.alarm_layout.count():
            item = self.alarm_layout.takeAt(0)
            if item:
                w = item.widget()
                if w:
                    w.deleteLater()

        search_text = self.search_line.text().strip().lower()

        for alarm_info in self.alarms_list:
            st = alarm_info.get('state_event', 2)
            if st not in (0, 1):
                continue

            panel_str = str(alarm_info.get('panel_id', '')).lower()
            if search_text and search_text not in panel_str:
                continue

            self.display_alarm_card(alarm_info)

    def display_alarm_card(self, alarm_info: dict):
        """Создает виджет-карточку тревоги."""
        panel_id = alarm_info.get('panel_id', 'UNKNOWN')
        st = alarm_info.get('state_event', 2)

        card = QWidget()
        # Присвоим objectName, чтобы можно было при remove_alarm_card найти
        card.setObjectName(f"alarm-card-{panel_id}")
        card.setProperty("stateEvent", st)

        card.style().unpolish(card)
        card.style().polish(card)
        card.update()

        layout = QVBoxLayout(card)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(5)

        # Заголовок
        header_layout = QHBoxLayout()
        panel_label = QLabel(f"Объект: {panel_id}")
        panel_label.setObjectName("alarm-panel-label")
        panel_label.setProperty("stateEvent", st)
        panel_label.style().unpolish(panel_label)
        panel_label.style().polish(panel_label)
        panel_label.update()

        tm = alarm_info.get('time_event')
        if not tm:
            tm = datetime.now()
        if isinstance(tm, datetime):
            tm_str = tm.strftime('%Y-%m-%d %H:%M:%S')
        else:
            tm_str = str(tm)
        time_label = QLabel(tm_str)
        time_label.setObjectName("alarm-time-label")

        header_layout.addWidget(panel_label)
        header_layout.addStretch()
        header_layout.addWidget(time_label)
        layout.addLayout(header_layout)

        # Остальные поля
        code_label = QLabel(f"Код события: {alarm_info.get('code','')}")
        company_label = QLabel(f"Название объекта: {alarm_info.get('company_name','')}")
        address_label = QLabel(f"Адрес: {alarm_info.get('address','')}")
        phone_label = QLabel(f"Телефон: {alarm_info.get('phone_number','N/A')}")

        layout.addWidget(code_label)
        layout.addWidget(company_label)
        layout.addWidget(address_label)
        layout.addWidget(phone_label)

        # Кнопка «Подробнее»
        details_btn = QPushButton("Подробнее")
        details_btn.setObjectName("details-button")
        details_btn.clicked.connect(lambda: self.show_alarm_details(panel_id))
        layout.addWidget(details_btn)

        self.alarm_layout.addWidget(card)

    def show_alarm_details(self, panel_id):
        """Открываем диалоговое окно подробностей для данного panel_id."""
        alarms_info = [a for a in self.alarms_list if a.get('panel_id') == panel_id]
        if not alarms_info:
            return

        responsibles = []
        for alarm in alarms_info:
            r_name = alarm.get('responsible_name', 'Неизвестно')
            r_phone = alarm.get('phone_number', 'Неизвестен')
            r_addr = alarm.get('responsible_address', 'Неизвестен')
            responsibles.append({
                'name': r_name,
                'phone': r_phone,
                'address': r_addr
            })

        dialog = AlarmDetailsDialog(alarms_info, responsibles, parent=self)
        dialog.setStyleSheet(self.styleSheet())
        dialog.exec_()

    # ---------------- Методы для EventProcessor ----------------
    def remove_alarm_card(self, panel_id):
        """
        Удаляет карточку (виджет) по panel_id.
        """
        for i in range(self.alarm_layout.count()):
            item = self.alarm_layout.itemAt(i)
            if not item:
                continue
            w = item.widget()
            if w and w.objectName() == f"alarm-card-{panel_id}":
                self.alarm_layout.removeWidget(w)
                w.deleteLater()
                # Также можно удалить саму тревогу из self.alarms_list
                self.alarms_list = [a for a in self.alarms_list if a.get('panel_id') != panel_id]
                self.displayed_alarms.discard(panel_id)
                self.logger.info(f"Тревога {panel_id} убрана из интерфейса.")
                break

    # ---------------- Подключение (БД, тел., SMS) ----------------
    def load_and_connect_db(self):
        """Подключение к БД (не закрываем программу, если неудачно)."""
        if 'Database' not in self.config:
            self.logger.error("Секция [Database] отсутствует в config.")
            return

        self.db_connector = DBConnector(self.config, parent=self)
        if self.db_connector.connect():
            self.update_status_widget(self.db_status, "Подключено")
            self.logger.info("Подключение к базе данных успешно.")
        else:
            self.update_status_widget(self.db_status, "Отключено")
            self.logger.error("Не удалось подключиться к базе данных.")

    def update_status_widget(self, widget, status):
        """Меняем label внутри `widget` (см. create_status_widget)."""
        status_lbl = widget.findChild(QLabel, "status_label")
        if not status_lbl:
            self.logger.error("Не найден QLabel(status_label) в update_status_widget.")
            return
        status_lbl.setText(status)
        status_lbl.setStyleSheet("color: green;" if status == "Подключено" else "color: red;")

    def handle_call_event(self, action_id, event_type, call_info, status=None):
        """Обработка событий IP-телефонии."""
        event_id = call_info.get('event_id','N/A')
        self.logger.extra['event_id'] = event_id

        if event_type == 'initiated':
            if status == 'Success':
                self.logger.info(f"Звонок инициирован: ActionID={action_id}")
            else:
                self.logger.error(f"Не удалось инициировать звонок: ActionID={action_id}")
        elif event_type == 'dial':
            if status == 'ANSWER':
                self.logger.info(f"Звонок принят: ActionID={action_id}")
            else:
                self.logger.warning(f"Звонок не принят: ActionID={action_id}, Status={status}")
        elif event_type == 'hangup':
            self.logger.info(f"Звонок завершен: ActionID={action_id}, Status={status}")

        self.logger.extra['event_id'] = 'N/A'

    def load_and_connect_telephony(self):
        """Подключение к Asterisk."""
        if 'Asterisk' in self.config:
            try:
                self.telephony_manager = CallManager(self.config, callback=self.handle_call_event)
                self.update_status_widget(self.telephony_status, "Подключено")
                self.logger.info("Подключение к IP-телефонии успешно.")
            except Exception as e:
                self.update_status_widget(self.telephony_status, "Отключено")
                self.logger.error(f"Ошибка подключения к IP-телефонии: {e}")
                QMessageBox.critical(self, "Ошибка IP-телефонии", str(e))
        else:
            self.update_status_widget(self.telephony_status, "Отключено")
            self.logger.error("В конфигурации нет секции [Asterisk].")

    def load_and_connect_sms_gateway(self):
        """Проверка SMS-шлюза (HTTP)."""
        if 'SMS' in self.config:
            sms_section = self.config['SMS']
            url = sms_section.get('url','')
            login = sms_section.get('login','')
            password = sms_section.get('password','')
            if self.check_http_connection(url, login, password):
                self.update_status_widget(self.sms_status, "Подключено")
                self.logger.info("Подключение к SMS-шлюзу успешно.")
            else:
                self.update_status_widget(self.sms_status, "Отключено")
                self.logger.error("Не удалось подключиться к SMS-шлюзу.")
        else:
            self.logger.error("Секция [SMS] отсутствует в конфиге.")

    def check_http_connection(self, url, login, password):
        """Пинг SMS-шлюза."""
        try:
            r = requests.get(
                url,
                params={'login': login, 'password': password, 'operation': 'ping'},
                timeout=5
            )
            if r.status_code == 200:
                self.logger.info("Успешное соединение с HTTP SMS-шлюзом")
                return True
            else:
                self.logger.error(f"HTTP SMS-шлюз вернул статус {r.status_code}")
                return False
        except requests.RequestException as e:
            self.logger.error(f"Ошибка при соединении с SMS-шлюзом: {e}")
            return False

    # ---------------- Таймеры ----------------
    def setup_timers(self):
        """Таймеры для обновления тревог и проверки статуса."""
        self.alarm_timer = QTimer(self)
        self.alarm_timer.timeout.connect(self.update_alarms)
        self.alarm_timer.start(10_000)

        self.status_timer = QTimer(self)
        self.status_timer.timeout.connect(self.check_system_status)
        self.status_timer.start(10_000)

    def update_alarms(self):
        """Запустить мониторинг, если не запущен."""
        self.logger.info("Начато обновление списка тревог.")
        if self.monitoring and not self.monitoring.isRunning():
            self.monitoring.start()
            self.logger.info("Мониторинг тревог запущен.")

    def check_system_status(self):
        """Проверка БД, телефонии, SMS."""
        self.load_and_connect_db()
        self.load_and_connect_telephony()
        self.load_and_connect_sms_gateway()
        self.logger.info("Проверка состояния системы завершена.")

    # ---------------- Обработка тревог (Monitoring) ----------------
    def process_alarms(self, alarms):
        """
        alarms — список словарей (StateEvent=0 или 1) от monitoring.py.
        Дополняем self.alarms_list, перерисовываем карточки.
        """
        alarm_handler = AlarmHandler(self.db_connector)

        for alarm in alarms:
            st = alarm.get('StateEvent', 2)
            if st not in (0, 1):
                continue

            panel_id = alarm.get('Panel_id')
            if not panel_id:
                self.logger.error(f"Отсутствует Panel_id в alarm: {alarm}")
                continue

            # Если такой panel_id уже есть — пропускаем
            already_in_list = any(a['panel_id'] == panel_id for a in self.alarms_list)
            if not already_in_list:
                alarm_info = alarm_handler.process_alarm(alarm)
                if not alarm_info:
                    continue

                # Переименовываем:
                alarm_info['panel_id'] = alarm_info.pop('Panel_id', panel_id)
                alarm_info['state_event'] = alarm_info.pop('StateEvent', st)
                alarm_info['time_event'] = alarm_info.pop('TimeEvent', None)
                alarm_info['code'] = alarm_info.pop('Code', '')

                if 'Responsible_Name' in alarm_info:
                    alarm_info['responsible_name'] = alarm_info.pop('Responsible_Name')
                if 'Responsible_Address' in alarm_info:
                    alarm_info['responsible_address'] = alarm_info.pop('Responsible_Address')
                if 'PhoneNo' in alarm_info:
                    alarm_info['phone_number'] = alarm_info.pop('PhoneNo')

                self.alarms_list.append(alarm_info)
                if self.db_connector and self.db_connector.connection:
                    self.event_processor.enqueue_event(alarm_info)

        self.update_alarm_cards()
        self.logger.info("События загружены в интерфейс и начата обработка.")

    # ---------------- Включение/Отключение обработки ----------------
    def toggle_event_processing(self):
        if self.processing_toggle_button.isChecked():
            self.processing_toggle_button.setText("Отключить обработку")
            if hasattr(self, 'event_processor') and self.event_processor and not self.event_processor.is_processing_active():
                self.event_processor.start_processing()
                self.logger.info("Обработка событий включена.")
        else:
            self.processing_toggle_button.setText("Включить обработку")
            if hasattr(self, 'event_processor') and self.event_processor and self.event_processor.is_processing_active():
                self.event_processor.stop_processing()
                self.logger.info("Обработка событий отключена.")

    # ---------------- О программе ----------------
    def show_about_dialog(self):
        QMessageBox.about(
            self,
            "О программе",
            (
                "SMENA - Система мониторинга событий и тревог.\n\n"
                "Разработчик: MrJin\n"
                "Версия: 1.0\n\n"
                "Цель системы:\n"
                "SMENA предназначена для мониторинга событий, генерации голосовых уведомлений, "
                "отправки SMS и взаимодействия с ответственными лицами в режиме реального времени. "
                "Программа обрабатывает события безопасности, технического состояния и другие критические оповещения.\n\n"
                "Ключевые возможности:\n"
                "- Мониторинг событий с различных источников;\n"
                "- Интеграция с IP-телефонией и SMS-шлюзами;\n"
                "- Генерация голосовых сообщений с использованием Yandex.Cloud;\n"
                "- Отправка SMS уведомлений;\n"
                "- Поддержка многозадачной обработки событий.\n\n"
                "Дата выпуска: Январь 2025\n\n"
                "Связь с разработчиком:\n"
                "Email: smena@mrjin.com\n"
                "Телеграм: @AlladinIT \n\n"
                "Дополнительная информация:\n"
                "Все права защищены. Использование ПО возможно только в соответствии с лицензией."
            )
        )

    # ---------------- Настройки / Диалоги ----------------
    def open_db_settings(self):
        dlg = QDialog(self)
        dlg.setWindowTitle("Настройки базы данных")
        dlg.setFixedSize(400, 300)
        layout = QFormLayout(dlg)

        if 'Database' not in self.config:
            self.config.add_section('Database')

        db_section = self.config['Database']

        server_input = QLineEdit(db_section.get('server',''))
        user_input = QLineEdit(db_section.get('user',''))
        password_input = QLineEdit(db_section.get('password',''))
        database_input = QLineEdit(db_section.get('database',''))

        layout.addRow("Имя SQL сервера:", server_input)
        layout.addRow("Имя пользователя:", user_input)
        layout.addRow("Пароль:", password_input)
        layout.addRow("База данных:", database_input)

        apply_btn = QPushButton("Применить")
        apply_btn.setIcon(QIcon(database_icon_path))

        def on_apply():
            s = server_input.text().strip()
            u = user_input.text().strip()
            p = password_input.text().strip()
            d = database_input.text().strip()

            if not s or not u or not d:
                QMessageBox.warning(self, "Ошибка", "Поля 'сервер','пользователь','база' обязательны.")
                return

            self.config['Database'] = {
                'server': s,
                'user': u,
                'password': p,
                'database': d
            }
            with open(config_path, 'w', encoding='utf-8') as cf:
                self.config.write(cf)

            self.db_connector = DBConnector(self.config, parent=self)
            if self.db_connector.connect():
                self.update_status_widget(self.db_status, "Подключено")
                self.logger.info("Подключение к базе данных успешно (apply).")
                QMessageBox.information(self, "Успех", "Подключено к базе данных!")
                dlg.close()

                if hasattr(self, 'monitoring') and self.monitoring:
                    self.monitoring.db_connector = self.db_connector
                else:
                    self.monitoring = MonitoringThread(self.db_connector)
                    self.monitoring.alarms_found.connect(self.process_alarms)
            else:
                self.update_status_widget(self.db_status, "Отключено")
                self.logger.error("Не удалось подключиться к базе (apply).")
                QMessageBox.critical(self, "Ошибка", "Не удалось подключиться к БД.")

        apply_btn.clicked.connect(on_apply)
        layout.addWidget(apply_btn)
        dlg.setLayout(layout)
        dlg.exec_()

    def open_telephony_settings(self):
        dlg = TelephonySettingsDialog(self)
        dlg.exec_()

    def open_sms_settings(self):
        dlg = SMSSettingsDialog(self)
        dlg.exec_()

    def open_voice_synth_settings(self):
        dlg = VoiceSynthesizerSettingsDialog(self)
        dlg.exec_()

    def open_code_dialog(self):
        dlg = CodeDialog(self)
        dlg.exec_()

    def open_message_dialog(self):
        dlg = MessageDialog(self)
        dlg.exec_()

    def open_event_processing_settings(self):
        dlg = EventProcessingSettingsDialog(self.config, self)
        if dlg.exec_():
            if hasattr(self, 'event_processor') and self.event_processor:
                self.event_processor.update_settings(dlg.get_settings())

    # ---------------- Трей / Закрытие ----------------
    def init_tray_icon(self):
        self.tray_icon = QSystemTrayIcon(QIcon(icon_16_path), self)
        tray_menu = QMenu(self)

        restore_action = QAction("Развернуть", self)
        restore_action.triggered.connect(self.show_normal)

        exit_action = QAction("Выход", self)
        exit_action.triggered.connect(self.close_application)

        tray_menu.addAction(restore_action)
        tray_menu.addAction(exit_action)

        self.tray_icon.setContextMenu(tray_menu)
        self.tray_icon.show()

    def close_application(self):
        self.tray_icon.hide()
        self.close()
        self.logger.info("Приложение закрыто пользователем.")

    def show_normal(self):
        self.show()
        self.setWindowState(Qt.WindowActive)
        self.raise_()
        self.activateWindow()
        self.logger.info("Окно приложения развернуто.")

    def closeEvent(self, event):
        reply = QMessageBox(self)
        reply.setWindowTitle('Закрыть программу')
        reply.setText("Вы хотите свернуть программу в трей или полностью закрыть?")
        reply.setStandardButtons(QMessageBox.Yes | QMessageBox.No)

        yes_btn = reply.button(QMessageBox.Yes)
        no_btn = reply.button(QMessageBox.No)

        yes_btn.setText("В Трей")
        no_btn.setText("Закрыть")

        result = reply.exec_()
        if result == QMessageBox.Yes:
            event.ignore()
            self.hide()
            self.logger.info("Программа свернута в трей (closeEvent).")
        else:
            event.accept()
            self.logger.info("Приложение закрывается пользователем (closeEvent).")
