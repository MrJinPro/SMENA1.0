from PyQt5.QtWidgets import QDialog, QVBoxLayout, QLabel, QLineEdit, QPushButton, QMessageBox
import configparser
import os
import re

# Используем абсолютный путь к файлу конфигурации
config_path = os.path.abspath(os.path.join(os.path.dirname(__file__), 'config.ini'))

class CodeDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Настройка кодов событий")

        layout = QVBoxLayout(self)

        layout.addWidget(QLabel("Введите коды событий через запятую (например: E302, Z5):"))

        self.codes_edit = QLineEdit()
        self.codes_edit.setText(self.load_event_codes_from_config())
        layout.addWidget(self.codes_edit)

        apply_button = QPushButton("Применить")
        apply_button.clicked.connect(self.save_event_codes_to_config)
        layout.addWidget(apply_button)

    def save_event_codes_to_config(self):
        codes = self.codes_edit.text().strip()

        if not self.validate_codes(codes):
            QMessageBox.warning(self, "Ошибка", "Коды событий должны быть в формате букв и цифр, разделенных запятой (например, E302, Z5).")
            return

        config = configparser.ConfigParser()
        config.read(config_path, encoding='utf-8')

        if not config.has_section('EventCodes'):
            config.add_section('EventCodes')
        config.set('EventCodes', 'codes', codes)

        with open(config_path, 'w', encoding='utf-8') as configfile:
             config.write(configfile)


        QMessageBox.information(self, "Сохранено", "Коды событий успешно сохранены!")
        self.accept()

    def validate_codes(self, codes):
        return all(re.match(r"^[A-Za-z0-9]+$", code.strip()) for code in codes.split(','))

    def load_event_codes_from_config(self):
        config = configparser.ConfigParser()
        config.read(config_path, encoding='utf-8')

        return config.get('EventCodes', 'codes', fallback="")
