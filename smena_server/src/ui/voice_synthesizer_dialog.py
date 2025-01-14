import os
import random
import requests
import configparser
from PyQt5.QtWidgets import QDialog, QFormLayout, QLineEdit, QComboBox, QSlider, QPushButton, QLabel, QMessageBox
from PyQt5.QtCore import Qt, QUrl
from PyQt5.QtMultimedia import QMediaPlayer, QMediaContent
import logging

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger('voice_synthezer_dialog')


# Доступные голоса (эмоции)
voice_emotions = {
    "alyss": ["neutral"],
    "oksana": ["neutral"],
    "jane": ["neutral", "good", "evil"],
    "omazh": ["neutral", "evil"],
    "filipp": ["neutral"],
    "ermil": ["neutral", "good"],
    "zahar": ["neutral", "good"],
    "dasha": ["neutral", "good", "friendly"],
    "julia": ["neutral", "strict"],
    "lera": ["neutral", "friendly"],
    "masha": ["good", "strict", "friendly"],
    "marina": ["neutral", "whisper", "friendly"],
    "alexander": ["neutral", "good"],
    "kirill": ["neutral", "strict", "good"],
    "anton": ["neutral", "good"]
}

class VoiceSynthesizerSettingsDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Настройки синтеза речи")
        self.setGeometry(300, 300, 400, 300)
        self.layout = QFormLayout(self)

        # Поля для ввода API-ключа и Folder ID
        self.api_key_input = QLineEdit()
        self.folder_id_input = QLineEdit()

        # Поле выбора голоса
        self.voice_input = QComboBox()
        self.voice_input.addItems(list(voice_emotions.keys()))
        self.voice_input.currentTextChanged.connect(self.update_emotion_options)

        # Поле для выбора эмоции
        self.emotion_input = QComboBox()
        
        # Поле для настройки скорости речи (ползунок)
        self.speed_slider = QSlider(Qt.Horizontal)
        self.speed_slider.setRange(50, 200)  # 0.5x до 2.0x скорости
        self.speed_slider.setValue(100)  # Значение по умолчанию — 1.0x
        self.speed_label = QLabel("1.0")  # Метка текущей скорости

        # Поле для ввода текста для синтеза
        self.text_input = QLineEdit()

        # Добавляем поля в форму
        self.layout.addRow("API-ключ:", self.api_key_input)
        self.layout.addRow("Folder ID:", self.folder_id_input)
        self.layout.addRow("Голос:", self.voice_input)
        self.layout.addRow("Эмоция:", self.emotion_input)
        self.layout.addRow("Скорость речи:", self.speed_slider)
        self.layout.addRow("Текущая скорость:", self.speed_label)
        self.layout.addRow("Текст для синтеза:", self.text_input)

        # Ползунок меняет значение метки скорости
        self.speed_slider.valueChanged.connect(self.update_speed_label)

        # Кнопки для тестирования, сохранения и отмены
        test_button = QPushButton("Тестировать синтез")
        test_button.clicked.connect(self.synthesize_voice)
        self.layout.addWidget(test_button)

        save_button = QPushButton("Сохранить настройки")
        save_button.clicked.connect(self.save_settings)
        self.layout.addWidget(save_button)

        cancel_button = QPushButton("Отмена")
        cancel_button.clicked.connect(self.reject)
        self.layout.addWidget(cancel_button)

        self.audio_file_path = None  # Для хранения пути к аудиофайлу
        
        # Инциализация плеера для воспроизведения
        self.media_player = QMediaPlayer()

        # Загрузка данных из конфигурации
        self.load_settings()

    def load_settings(self):
        """Загружает настройки из config.ini при инициализации"""
        config = configparser.ConfigParser()
        config_path = os.path.abspath(os.path.join(os.path.dirname(__file__), 'config.ini'))

        if os.path.exists(config_path):
            config.read(config_path, encoding='utf-8')
            
            if 'YandexCloud' in config:
                self.api_key_input.setText(config['YandexCloud'].get('api_key', ''))
                self.folder_id_input.setText(config['YandexCloud'].get('folder_id', ''))
                self.voice_input.setCurrentText(config['YandexCloud'].get('voice', 'alyss'))
                self.emotion_input.setCurrentText(config['YandexCloud'].get('emotion', 'neutral'))
                speed = float(config['YandexCloud'].get('speed', '1.0'))
                self.speed_slider.setValue(int(speed * 100))
                self.speed_label.setText(f"{speed:.1f}")
            else:
                QMessageBox.warning(self, "Ошибка", "Секция YandexCloud отсутствует в файле конфигурации.")
        else:
            QMessageBox.warning(self, "Ошибка", "Файл конфигурации не найден.")

    def update_emotion_options(self):
        """Обновление доступных эмоций в зависимости от выбраного голоса"""
        selected_voice = self.voice_input.currentText()
        emotions = voice_emotions.get(selected_voice, ["neutral"])

        # Очищаем старые эмоции и добавляем новые доступные для выбранного голоса
        self.emotion_input.clear()
        self.emotion_input.addItems(emotions)

    def update_speed_label(self):
        """Обновляет метку текущей скорости в зависимости от положения ползунка"""
        current_speed = self.speed_slider.value() / 100.0
        self.speed_label.setText(f"{current_speed:.1f}")

    def save_settings(self):
        """Сохраняет настройки в файл config.ini"""
        config = configparser.ConfigParser()
        config['YandexCloud'] = {
            'api_key': self.api_key_input.text().strip(),
            'folder_id': self.folder_id_input.text().strip(),
            'voice': self.voice_input.currentText(),
            'emotion': self.emotion_input.currentText(),
            'speed': self.speed_slider.value() / 100.0
        }
        config_path = os.path.abspath(os.path.join(os.path.dirname(__file__), 'config.ini'))
        with open(config_path, 'w', encoding='utf-8') as configfile:
            config.write(configfile)

        QMessageBox.information(self, "Сохранено", "Настройки успешно сохранены!")

    def synthesize_voice(self):
        """Синтезирует речь и сохраняет аудиофайл"""
        api_key = self.api_key_input.text().strip()
        folder_id = self.folder_id_input.text().strip()
        text = self.text_input.text().strip()
        voice = self.voice_input.currentText()
        emotion = self.emotion_input.currentText()
        speed = self.speed_slider.value() / 100.0

        if not api_key or not folder_id or not text:
            QMessageBox.warning(self, "Ошибка", "Все поля обязательны для заполнения.")
            return

        headers = {
            "Authorization": f"Api-Key {api_key}"
        }
        data = {
            "text": text,
            "lang": "ru-RU",
            "voice": voice,
            "speed": str(speed),
            "emotion": emotion,
            "folderId": folder_id
        }
        url = "https://tts.api.cloud.yandex.net/speech/v1/tts:synthesize"

        try:
            response = requests.post(url, headers=headers, data=data)
            response.raise_for_status()
        except requests.RequestException as e:
            QMessageBox.critical(self, "Ошибка", f"Ошибка запроса к API: {e}")
            return

        # Сохраняем сгенерированный аудиофайл
        random_number = random.randint(1000, 9999)
        self.audio_file_path = os.path.join(os.path.dirname(__file__), f'test_sintez_{random_number}.ogg')

        with open(self.audio_file_path, 'wb') as f:
            f.write(response.content)

        # Воспроизводим файл
        content = QMediaContent(QUrl.fromLocalFile(self.audio_file_path))
        self.media_player.setMedia(content)
        self.media_player.play()

    def closeEvent(self, event):
        """Удалим сгенерированный файл после закрытия окна"""
        if self.audio_file_path and os.path.exists(self.audio_file_path):
            try:
                os.remove(self.audio_file_path)
                logger.info(f"Аудиофайл {self.audio_file_path} удалён")
            except Exception as e:
                logger.info(f"Ошибка удаления аудиофайла: {e}")
        super().closeEvent(event)
