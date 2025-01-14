# event_processing_settings_dialog.py

import configparser
import os
from PyQt5.QtWidgets import QDialog, QFormLayout, QSpinBox, QPushButton, QMessageBox, QCheckBox

config_path = os.path.abspath(os.path.join(os.path.dirname(__file__), 'config.ini'))

class EventProcessingSettingsDialog(QDialog):
    def __init__(self, config, parent=None):
        super().__init__(parent)
        self.config = config
        self.setWindowTitle("Настройки обработки событий")

        # Правильная инициализация layout
        self.layout = QFormLayout()
        self.setLayout(self.layout)

        # Поле для ввода максимального количества одновременно обрабатываемых событий
        self.max_workers_input = QSpinBox()
        self.max_workers_input.setRange(1, 100)  # Устанавливаем диапазон значений
        self.layout.addRow("Максимальное количество событий:", self.max_workers_input)

        # Чекбокс для включения/отключения тестового режима
        self.test_mode_checkbox = QCheckBox("Включить тестовый режим")
        self.layout.addRow(self.test_mode_checkbox)

        # Кнопка для сохранения настроек
        save_button = QPushButton("Сохранить")
        save_button.clicked.connect(self.save_settings)
        self.layout.addWidget(save_button)

        # Загрузка текущих настроек
        self.load_settings()

    def load_settings(self):
        """Загрузка настроек из конфигурационного файла."""
        config = configparser.ConfigParser()
        config.read(config_path, encoding='utf-8')

        # Загрузка максимального количества событий
        if 'EventProcessing' in config:
            max_workers = config['EventProcessing'].getint('max_concurrent_events', 5)
            self.max_workers_input.setValue(max_workers)

        # Загрузка состояния тестового режима
        if 'Testing' in config:
            test_mode = config['Testing'].getboolean('test_mode', fallback=False)
            self.test_mode_checkbox.setChecked(test_mode)
        else:
            self.test_mode_checkbox.setChecked(False)  # По умолчанию тестовый режим выключен

    def save_settings(self):
        try:
            max_workers = self.max_workers_input.value()  # Получаем значение из QSpinBox
            test_mode = self.test_mode_checkbox.isChecked()  # Получаем состояние чекбокса

            # Обновляем настройки в конфигурации
            self.config['EventProcessing'] = {
                'max_concurrent_events': str(max_workers)
            }

            self.config['Testing'] = {
                'test_mode': str(test_mode).lower(),  # Преобразуем булево значение в строку 'true' или 'false'
                'test_phone_number': self.config['Testing'].get('test_phone_number', '')
            }

            # Сохраняем изменения в файле конфигурации
            with open(config_path, 'w', encoding='utf-8') as configfile:
                self.config.write(configfile)

            QMessageBox.information(self, "Сохранено", "Настройки сохранены!")
            self.accept()
        except ValueError:
            QMessageBox.warning(self, "Ошибка", "Пожалуйста, введите корректные значения для всех полей.")

    def get_settings(self):
        """Возвращает текущие настройки из диалогового окна."""
        return {
            'max_concurrent_events': self.max_workers_input.value(),
            'test_mode': self.test_mode_checkbox.isChecked()
        }
