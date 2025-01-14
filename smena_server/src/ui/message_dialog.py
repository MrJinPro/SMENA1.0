# ui/message_dialog.py

import configparser
import os
from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QLabel,  QTextEdit, QPushButton, QMessageBox, QFrame, QHBoxLayout, QToolButton, QCheckBox
)

from PyQt5.QtCore import Qt


config_path = os.path.abspath(os.path.join(os.path.dirname(__file__), 'config.ini'))

class MessageDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Настройка сообщения")
        self.setFixedSize(600, 600)  # Установите подходящий размер окна

        layout = QVBoxLayout(self)

        # Текстовое поле для ввода шаблона SMS
        layout.addWidget(QLabel("Шаблон SMS сообщения:"))
        self.sms_message_edit = QTextEdit()
        self.sms_message_edit.setPlainText(self.load_message_from_config('sms_text'))
        layout.addWidget(self.sms_message_edit)

        # Пример доступных переменных для SMS-шаблона
        layout.addWidget(QLabel("Доступные переменные для SMS-шаблона (кликните, чтобы вставить):"))
        self.add_clickable_variables(layout, self.sms_message_edit, is_ssml=False)

        # Разделительная полоса
        separator_line_1 = QFrame()
        separator_line_1.setFrameShape(QFrame.HLine)
        separator_line_1.setFrameShadow(QFrame.Sunken)
        layout.addWidget(separator_line_1)

        # Текстовое поле для ввода шаблона для синтеза речи
        layout.addWidget(QLabel("Шаблон для синтеза речи (SSML):"))
        self.tts_message_edit = QTextEdit()
        self.tts_message_edit.setPlainText(self.load_message_from_config('tts_text'))
        layout.addWidget(self.tts_message_edit)

        # Пример доступных переменных и SSML тегов для синтеза речи
        layout.addWidget(QLabel("Доступные переменные и SSML теги (кликните, чтобы вставить):"))
        self.add_clickable_variables(layout, self.tts_message_edit, is_ssml=True)

        # Чекбокс для включения/отключения SSML
        self.ssml_checkbox = QCheckBox("Использовать SSML для синтеза речи")
        self.ssml_checkbox.setToolTip("SSML (Speech Synthesis Markup Language) позволяет более гибко управлять произношением текста, включая паузы, ударения и другие элементы.")
        self.ssml_checkbox.setChecked(self.load_ssml_setting())
        layout.addWidget(self.ssml_checkbox)

        # Разделительная полоса
        separator_line_2 = QFrame()
        separator_line_2.setFrameShape(QFrame.HLine)
        separator_line_2.setFrameShadow(QFrame.Sunken)
        layout.addWidget(separator_line_2)

        

        # Кнопка для сохранения
        apply_button = QPushButton("Применить")
        apply_button.clicked.connect(self.save_messages_to_config)
        layout.addWidget(apply_button)

    def add_clickable_variables(self, layout, text_edit, is_ssml):
        """
        Добавляет кнопки для вставки переменных и тегов в текстовое поле.
        :param layout: основной макет окна
        :param text_edit: поле для ввода текста
        :param is_ssml: если True, добавляем SSML теги
        """
        button_layout = QHBoxLayout()

        # Стандартные переменные
        variables = ["{object_id}", "{event_code}", "{event_time}", "{responsible_name}", "{address}"]

        for variable in variables:
            btn = QToolButton(self)
            btn.setText(variable)
            btn.clicked.connect(lambda _, v=variable: self.insert_text(text_edit, v))
            button_layout.addWidget(btn)

        if is_ssml:
            # Добавляем SSML теги
            ssml_tags = {
                
            }

            for tag, description in ssml_tags.items():
                btn = QToolButton(self)
                btn.setText(description)
                btn.clicked.connect(lambda _, t=tag: self.insert_text(text_edit, t))
                button_layout.addWidget(btn)

        layout.addLayout(button_layout)

    def insert_text(self, text_edit, text):
        """
        Вставляет текст в текстовое поле.
        :param text_edit: текстовое поле
        :param text: текст для вставки
        """
        cursor = text_edit.textCursor()
        cursor.insertText(text)

    def save_messages_to_config(self):
        """Сохраняем SMS и TTS сообщения в конфиг файл."""
        sms_message = self.sms_message_edit.toPlainText().strip()
        tts_message = self.tts_message_edit.toPlainText().strip()
        use_ssml = self.ssml_checkbox.isChecked()

        config = configparser.ConfigParser()
        config.read(config_path, encoding='utf-8')

        if not config.has_section('Message'):
            config.add_section('Message')

        config.set('Message', 'sms_text', sms_message)
        config.set('Message', 'tts_text', tts_message)
        config.set('Message', 'use_ssml', str(use_ssml))  # Сохраняем состояние SSML

        with open(config_path, 'w', encoding='utf-8') as configfile:
            config.write(configfile)

        QMessageBox.information(self, "Сохранено", "Сообщения и настройки SSML успешно сохранены!")
        self.accept()

    def load_message_from_config(self, key):
        """Загрузка сообщения из конфиг файла с правильной кодировкой."""
        config = configparser.ConfigParser()
        config.read(config_path, encoding='utf-8')
        return config.get('Message', key, fallback="")

    def load_ssml_setting(self):
        """Загрузка настройки использования SSML из конфиг файла."""
        config = configparser.ConfigParser()
        config.read(config_path, encoding='utf-8')
        return config.getboolean('Message', 'use_ssml', fallback=False)
