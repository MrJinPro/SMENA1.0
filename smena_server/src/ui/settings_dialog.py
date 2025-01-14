import configparser
from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout, QLabel, QLineEdit, QPushButton, QWidget, QMessageBox, QTabWidget
)


class SettingsDialog(QDialog):
    def __init__(self, config, parent=None):
        super().__init__(parent)
        self.config = config
        self.setWindowTitle("Настройки системы")
        self.layout = QVBoxLayout(self)

        # Создаем вкладки для разных категорий настроек
        self.tab_widget = QTabWidget()
        self.layout.addWidget(self.tab_widget)

        # Добавляем вкладки с настройками
        self.add_database_tab()
        self.add_telephony_tab()
        self.add_sms_tab()
        self.add_voice_synth_tab()

        # Кнопки "Применить" и "Отмена"
        button_layout = QHBoxLayout()
        apply_button = QPushButton("Применить")
        apply_button.clicked.connect(self.save_settings)
        cancel_button = QPushButton("Отмена")
        cancel_button.clicked.connect(self.reject)

        button_layout.addWidget(apply_button)
        button_layout.addWidget(cancel_button)

        self.layout.addLayout(button_layout)

    def add_database_tab(self):
        """Создаем вкладку с настройками базы данных"""
        db_tab = QWidget()
        db_layout = QFormLayout()

        self.db_server_input = QLineEdit(self.config['Database'].get('server', ''))
        self.db_user_input = QLineEdit(self.config['Database'].get('user', ''))
        self.db_password_input = QLineEdit(self.config['Database'].get('password', ''))
        self.db_database_input = QLineEdit(self.config['Database'].get('database', ''))

        db_layout.addRow("SQL сервер:", self.db_server_input)
        db_layout.addRow("Пользователь:", self.db_user_input)
        db_layout.addRow("Пароль:", self.db_password_input)
        db_layout.addRow("База данных:", self.db_database_input)

        db_tab.setLayout(db_layout)
        self.tab_widget.addTab(db_tab, "База данных")

    def add_telephony_tab(self):
        """Создаем вкладку с настройками IP-телефонии"""
        telephony_tab = QWidget()
        telephony_layout = QFormLayout()

        self.telephony_host_input = QLineEdit(self.config['Telephony'].get('host', ''))
        self.telephony_port_input = QLineEdit(self.config['Telephony'].get('port', ''))
        self.telephony_user_input = QLineEdit(self.config['Telephony'].get('user', ''))
        self.telephony_password_input = QLineEdit(self.config['Telephony'].get('password', ''))

        telephony_layout.addRow("Хост:", self.telephony_host_input)
        telephony_layout.addRow("Порт:", self.telephony_port_input)
        telephony_layout.addRow("Пользователь:", self.telephony_user_input)
        telephony_layout.addRow("Пароль:", self.telephony_password_input)

        telephony_tab.setLayout(telephony_layout)
        self.tab_widget.addTab(telephony_tab, "IP-телефония")

    def add_sms_tab(self):
        """Создаем вкладку с настройками SMS-шлюза"""
        sms_tab = QWidget()
        sms_layout = QFormLayout()

        self.sms_ip_input = QLineEdit(self.config['SMPP'].get('ip', ''))
        self.sms_port_input = QLineEdit(self.config['SMPP'].get('port', ''))
        self.sms_system_id_input = QLineEdit(self.config['SMPP'].get('system_id', ''))
        self.sms_password_input = QLineEdit(self.config['SMPP'].get('password', ''))

        sms_layout.addRow("IP шлюза:", self.sms_ip_input)
        sms_layout.addRow("Порт шлюза:", self.sms_port_input)
        sms_layout.addRow("System ID:", self.sms_system_id_input)
        sms_layout.addRow("Пароль:", self.sms_password_input)

        sms_tab.setLayout(sms_layout)
        self.tab_widget.addTab(sms_tab, "SMS-шлюз")

    def add_voice_synth_tab(self):
        """Создаем вкладку с настройками синтеза речи"""
        voice_synth_tab = QWidget()
        voice_synth_layout = QFormLayout()

        self.voice_synth_api_key_input = QLineEdit(self.config['YandexCloud'].get('api_key', ''))
        self.voice_synth_folder_id_input = QLineEdit(self.config['YandexCloud'].get('folder_id', ''))

        voice_synth_layout.addRow("API ключ:", self.voice_synth_api_key_input)
        voice_synth_layout.addRow("ID папки:", self.voice_synth_folder_id_input)

        voice_synth_tab.setLayout(voice_synth_layout)
        self.tab_widget.addTab(voice_synth_tab, "Синтез речи")

    def save_settings(self):
        """Сохраняем настройки в конфигурационный файл"""
        self.config['Database'] = {
            'server': self.db_server_input.text(),
            'user': self.db_user_input.text(),
            'password': self.db_password_input.text(),
            'database': self.db_database_input.text()
        }

        self.config['Telephony'] = {
            'host': self.telephony_host_input.text(),
            'port': self.telephony_port_input.text(),
            'user': self.telephony_user_input.text(),
            'password': self.telephony_password_input.text()
        }

        self.config['SMPP'] = {
            'ip': self.sms_ip_input.text(),
            'port': self.sms_port_input.text(),
            'system_id': self.sms_system_id_input.text(),
            'password': self.sms_password_input.text()
        }

        self.config['YandexCloud'] = {
            'api_key': self.voice_synth_api_key_input.text(),
            'folder_id': self.voice_synth_folder_id_input.text()
        }

        with open('config.ini', 'w') as configfile:
            self.config.write(configfile)

        QMessageBox.information(self, "Настройки", "Настройки сохранены!")
        self.accept()
