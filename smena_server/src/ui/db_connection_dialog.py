import configparser
from PyQt5.QtWidgets import QDialog, QFormLayout, QLineEdit, QPushButton, QMessageBox
from PyQt5.QtGui import QIcon

config = configparser.ConfigParser()

class DBConnectionDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Настройки базы данных")
        self.setFixedSize(400, 200)  # Фиксированный размер окна для более аккуратного вида

        self.layout = QFormLayout(self)

        # Поля ввода с плейсхолдерами для удобства
        self.server_input = QLineEdit()
        self.server_input.setPlaceholderText("Введите имя сервера")

        self.user_input = QLineEdit()
        self.user_input.setPlaceholderText("Введите имя пользователя")

        self.password_input = QLineEdit()
        self.password_input.setPlaceholderText("Введите пароль")
        self.password_input.setEchoMode(QLineEdit.Password)  # Скроем пароль

        self.database_input = QLineEdit()
        self.database_input.setPlaceholderText("Введите название базы данных")

        # Добавляем виджеты в форму
        self.layout.addRow("Имя SQL сервера:", self.server_input)
        self.layout.addRow("Имя пользователя:", self.user_input)
        self.layout.addRow("Пароль:", self.password_input)
        self.layout.addRow("База данных:", self.database_input)

        # Загрузка сохраненных настроек
        self.load_settings()

        apply_button = QPushButton("Применить")
        apply_button.setIcon(QIcon('resources/icons/apply.png'))  # Иконка для кнопки
        apply_button.clicked.connect(self.save_settings)
        self.layout.addWidget(apply_button)

    def load_settings(self):
        config.read('config.ini')
        if 'Database' in config:
            self.server_input.setText(config['Database'].get('server', ''))
            self.user_input.setText(config['Database'].get('user', ''))
            self.password_input.setText(config['Database'].get('password', ''))
            self.database_input.setText(config['Database'].get('database', ''))

    def save_settings(self):
        config['Database'] = {
            'server': self.server_input.text(),
            'user': self.user_input.text(),
            'password': self.password_input.text(),
            'database': self.database_input.text()
        }
        with open('config.ini', 'w', encoding='utf-8') as configfile:
            config.write(configfile)
        QMessageBox.information(self, "Сохранено", "Настройки базы данных сохранены!")
        self.accept()
