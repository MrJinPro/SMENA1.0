# telephony_settings_dialog.py

import os
import configparser
from PyQt5.QtWidgets import QDialog, QFormLayout, QLineEdit, QPushButton, QMessageBox, QLabel, QGroupBox, QVBoxLayout
from PyQt5.QtCore import Qt
from ui.call_manager import CallManager
import logging

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger('telephony_settings_dialog')


config = configparser.ConfigParser()
current_dir = os.path.dirname(os.path.abspath(__file__))
config_path = os.path.abspath(os.path.join(current_dir, 'config.ini'))


class TelephonySettingsDialog(QDialog):
    def __init__(self, parent=None, call_manager=None):
        super().__init__(parent)
        self.setWindowTitle("Настройки IP-телефонии")
        self.setWindowModality(Qt.ApplicationModal)  # Модальное окно
        self.setGeometry(300, 300, 400, 600)
        self.call_manager = call_manager  # Используем переданный call_manager

        # Основной макет
        main_layout = QVBoxLayout(self)

        # Группа настроек Telephony
        telephony_group = QGroupBox("Настройки Telephony")
        self.telephony_layout = QFormLayout()
        telephony_group.setLayout(self.telephony_layout)

        self.host_input = QLineEdit()
        self.port_input = QLineEdit()
        self.user_input = QLineEdit()
        self.password_input = QLineEdit()
        self.password_input.setEchoMode(QLineEdit.Password)  # Пароль скрыт

        self.telephony_layout.addRow("Host (IP):", self.host_input)
        self.telephony_layout.addRow("Port:", self.port_input)
        self.telephony_layout.addRow("Имя пользователя:", self.user_input)
        self.telephony_layout.addRow("Пароль:", self.password_input)

        # Группа настроек CDRDatabase
        cdr_group = QGroupBox("Настройки CDRDatabase")
        self.cdr_layout = QFormLayout()
        cdr_group.setLayout(self.cdr_layout)

        self.cdr_host_input = QLineEdit()
        self.cdr_port_input = QLineEdit()
        self.cdr_user_input = QLineEdit()
        self.cdr_password_input = QLineEdit()
        self.cdr_password_input.setEchoMode(QLineEdit.Password)
        self.cdr_database_input = QLineEdit()
        self.cdr_table_input = QLineEdit()

        self.cdr_layout.addRow("Host (IP):", self.cdr_host_input)
        self.cdr_layout.addRow("Port:", self.cdr_port_input)
        self.cdr_layout.addRow("Имя пользователя:", self.cdr_user_input)
        self.cdr_layout.addRow("Пароль:", self.cdr_password_input)
        self.cdr_layout.addRow("База данных:", self.cdr_database_input)
        self.cdr_layout.addRow("Таблица:", self.cdr_table_input)

        # Поля для тестов
        self.test_phone_input = QLineEdit()
        self.audio_file_input = QLineEdit()

        test_group = QGroupBox("Тестовые настройки")
        self.test_layout = QFormLayout()
        test_group.setLayout(self.test_layout)

        self.test_layout.addRow("Тестовый номер телефона:", self.test_phone_input)
        self.test_layout.addRow("Имя аудиофайла (без расширения):", self.audio_file_input)

        # Кнопки
        self.apply_button = QPushButton("Применить")
        self.apply_button.clicked.connect(self.save_settings)

        self.test_button = QPushButton("Тестировать звонок")
        self.test_button.clicked.connect(self.test_call)

        # Статус тестового звонка
        self.test_status_label = QLabel("")

        # Добавляем все элементы в основной макет
        main_layout.addWidget(telephony_group)
        main_layout.addWidget(cdr_group)
        main_layout.addWidget(test_group)
        main_layout.addWidget(self.apply_button)
        main_layout.addWidget(self.test_button)
        main_layout.addWidget(QLabel("Статус тестового звонка:"))
        main_layout.addWidget(self.test_status_label)

        self.load_settings()

    def load_settings(self):
        """Загружает настройки из файла config.ini"""
        logger.info("(Настройки) Загрузка настроек из config.ini...")
        if os.path.exists(config_path):
            config.read(config_path, encoding='utf-8')

            if 'Telephony' in config:
                logger.info(f"(Настройки) Настройки Telephony загружены.")
                self.host_input.setText(config['Telephony'].get('host', ''))
                self.port_input.setText(config['Telephony'].get('port', ''))
                self.user_input.setText(config['Telephony'].get('user', ''))
                self.password_input.setText(config['Telephony'].get('password', ''))

            if 'CDRDatabase' in config:
                logger.info(f"(Настройки) Настройки CDRDatabase загружены.")
                self.cdr_host_input.setText(config['CDRDatabase'].get('host', ''))
                self.cdr_port_input.setText(config['CDRDatabase'].get('port', ''))
                self.cdr_user_input.setText(config['CDRDatabase'].get('user', ''))
                self.cdr_password_input.setText(config['CDRDatabase'].get('password', ''))
                self.cdr_database_input.setText(config['CDRDatabase'].get('database', ''))
                self.cdr_table_input.setText(config['CDRDatabase'].get('table', ''))

    def save_settings(self):
        """Сохраняет настройки в config.ini и проверяет на корректность"""
        # Telephony settings
        host = self.host_input.text().strip()
        port = self.port_input.text().strip()
        user = self.user_input.text().strip()
        password = self.password_input.text().strip()

        # CDRDatabase settings
        cdr_host = self.cdr_host_input.text().strip()
        cdr_port = self.cdr_port_input.text().strip()
        cdr_user = self.cdr_user_input.text().strip()
        cdr_password = self.cdr_password_input.text().strip()
        cdr_database = self.cdr_database_input.text().strip()
        cdr_table = self.cdr_table_input.text().strip()

        if not host or not port or not user or not password:
            QMessageBox.warning(self, "Ошибка", "Все поля Telephony обязательны для заполнения.")
            return

        if not cdr_host or not cdr_port or not cdr_user or not cdr_password or not cdr_database or not cdr_table:
            QMessageBox.warning(self, "Ошибка", "Все поля CDRDatabase обязательны для заполнения.")
            return

        logger.info(f"(Настройки) Сохраняем настройки Telephony: host={host}, port={port}, user={user}")
        logger.info(f"(Настройки) Сохраняем настройки CDRDatabase: host={cdr_host}, port={cdr_port}, user={cdr_user}, database={cdr_database}, table={cdr_table}")

        # Сохраняем настройки
        config['Telephony'] = {
            'host': host,
            'port': port,
            'user': user,
            'password': password
        }

        config['CDRDatabase'] = {
            'host': cdr_host,
            'port': cdr_port,
            'user': cdr_user,
            'password': cdr_password,
            'database': cdr_database,
            'table': cdr_table
        }

        try:
            with open(config_path, 'w', encoding='utf-8') as configfile:
                config.write(configfile)
            logger.info("(Настройки) Настройки успешно сохранены!")
            QMessageBox.information(self, "Сохранено", "Настройки сохранены!")
            self.accept()

            # Переподключение CallManager с новыми настройками, если необходимо
            if self.call_manager:
                self.call_manager.stop()
                try:
                    new_call_manager = CallManager(host, int(port), user, password, self.parent().handle_call_event)
                    self.call_manager = new_call_manager
                    self.parent().db_connector.call_manager = new_call_manager  # Обновляем ссылку в главном окне
                    QMessageBox.information(self, "Переподключено", "CallManager успешно переподключен с новыми настройками.")
                except Exception as e:
                    QMessageBox.critical(self, "Ошибка", f"Не удалось переподключить CallManager: {e}")
        except Exception as e:
            QMessageBox.critical(self, "Ошибка", f"Не удалось сохранить настройки: {e}")

    def test_call(self):
        """Тестирует звонок с указанным номером и аудиофайлом"""
        phone_number = self.test_phone_input.text().strip()
        audio_file = self.audio_file_input.text().strip()

        if not phone_number or not audio_file:
            QMessageBox.warning(self, "Ошибка", "Введите номер телефона и имя аудиофайла.")
            return

        # Формируем имя файла без пути и расширения
        file_name = os.path.basename(audio_file)
        file_name = os.path.splitext(file_name)[0]

        logger.info(f"Попытка вызова: Номер={phone_number}, Имя файла={file_name}")

        # Проверка подключения: если уже подключено, не создаём новый CallManager
        if self.call_manager and self.call_manager.is_connected():
            action_id, uniqueid = self.call_manager.make_call(phone_number, file_name)
            if action_id:
                logger.info(f"(Настройки) Звонок на {phone_number} выполнен успешно.")
                QMessageBox.information(self, "Тест", f"Звонок на {phone_number} с файлом {file_name} выполнен успешно.")
                self.test_status_label.setText("Тестовый звонок выполнен успешно.")
            else:
                logger.info(f"(Настройки) Не удалось выполнить звонок на {phone_number}.")
                QMessageBox.warning(self, "Ошибка", "Не удалось выполнить звонок.")
                self.test_status_label.setText("Тестовый звонок не выполнен.")
        else:
            logger.info("(Настройки) Не удалось подключиться к Asterisk.")
            QMessageBox.warning(self, "Ошибка", "Не удалось подключиться к Asterisk.")
            self.test_status_label.setText("Не удалось подключиться к Asterisk.")
