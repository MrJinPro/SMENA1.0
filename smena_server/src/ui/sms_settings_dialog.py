import configparser
from PyQt5.QtWidgets import QDialog, QFormLayout, QLineEdit, QPushButton, QMessageBox
import os
from ui.sms_manager import send_http_sms

# Загрузка конфигурации
config = configparser.ConfigParser()
config_path = os.path.abspath(os.path.join(os.path.dirname(__file__), 'config.ini'))

class SMSSettingsDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Настройки SMS-шлюза")
        self.layout = QFormLayout(self)

        # Поля для ввода логина, пароля и имени отправителя для HTTP API
        self.login_input = QLineEdit()
        self.password_input = QLineEdit()
        self.password_input.setEchoMode(QLineEdit.Password)  # Пароль скрыт
        self.sender_name_input = QLineEdit()

        # Добавляем поля в диалоговое окно
        self.layout.addRow("Логин:", self.login_input)
        self.layout.addRow("Пароль:", self.password_input)
        self.layout.addRow("Имя отправителя:", self.sender_name_input)

        # Поля для тестирования SMS
        self.test_phone_input = QLineEdit()
        self.test_message_input = QLineEdit()
        self.layout.addRow("Номер телефона (для теста):", self.test_phone_input)
        self.layout.addRow("Текст сообщения (для теста):", self.test_message_input)

        # Кнопка для отправки тестового SMS
        test_button = QPushButton("Отправить тестовое SMS")
        test_button.clicked.connect(self.send_test_sms)
        self.layout.addWidget(test_button)

        # Кнопка для сохранения настроек
        apply_button = QPushButton("Применить")
        apply_button.clicked.connect(self.save_settings)
        self.layout.addWidget(apply_button)

        self.load_settings()

    def load_settings(self):
        """Загрузка настроек из конфигурационного файла."""
        config.read(config_path, encoding='utf-8')

        if 'SMS' in config:
            self.login_input.setText(config['SMS'].get('login', ''))
            self.password_input.setText(config['SMS'].get('password', ''))
            self.sender_name_input.setText(config['SMS'].get('shortcode', 'ZD_ohrana'))

    def save_settings(self):
        """Сохранение настроек в конфигурационный файл."""
        login = self.login_input.text().strip()
        password = self.password_input.text().strip()
        sender_name = self.sender_name_input.text().strip()

        # Проверка на заполненность полей
        if not login or not password or not sender_name:
            QMessageBox.warning(self, "Ошибка", "Все поля обязательны для заполнения.")
            return

        # Сохранение данных в конфигурационный файл
        config['SMS'] = {
            'login': login,
            'password': password,
            'shortcode': sender_name
        }

        try:
            with open(config_path, 'w') as configfile:
                config.write(configfile)
            QMessageBox.information(self, "Сохранено", "Настройки HTTP сохранены!")
            self.accept()
        except Exception as e:
            QMessageBox.critical(self, "Ошибка", f"Не удалось сохранить настройки: {e}")

    def send_test_sms(self):
        """Отправка тестового SMS на введённый номер с введённым текстом."""
        phone_number = self.test_phone_input.text().strip()
        message = self.test_message_input.text().strip()

        if not phone_number or not message:
            QMessageBox.warning(self, "Ошибка", "Необходимо ввести номер телефона и текст сообщения для теста.")
            return

        # Используем сохранённые настройки для отправки сообщения
        login = self.login_input.text().strip()
        password = self.password_input.text().strip()
        sender_name = self.sender_name_input.text().strip()
        url = config['SMS'].get('url', 'https://bsms.tele2.ru/api/send')

        # Передаем параметры в функцию отправки SMS
        success = send_http_sms(
            phone_number, 
            message, 
            url=url, 
            login=login, 
            password=password, 
            shortcode=sender_name
        )

        if success:
            QMessageBox.information(self, "Успех", "Тестовое SMS успешно отправлено!")
        else:
            QMessageBox.critical(self, "Ошибка", "Ошибка при отправке тестового SMS.")
