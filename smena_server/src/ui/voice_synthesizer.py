import os
import requests
import threading
from http.server import HTTPServer, SimpleHTTPRequestHandler
from urllib.parse import urljoin
from pydub import AudioSegment
import configparser
import logging

# Настройка глобального логирования
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger('Syntez')

# Отключение логов от pydub.converter
logging.getLogger("pydub.converter").setLevel(logging.WARNING)  # Или logging.ERROR

config_path = os.path.abspath(os.path.join(os.path.dirname(__file__), 'config.ini'))

def load_message_template():
    """Загрузка сообщения из конфиг файла с правильной кодировкой UTF-8."""
    config = configparser.ConfigParser()
    config.read(config_path, encoding='utf-8')
    return config.get('Message', 'text', fallback="")

def load_synthesizer_settings():
    """Загрузка параметров синтеза речи из конфиг файла."""
    config = configparser.ConfigParser()
    config.read(config_path, encoding='utf-8')

    settings = {
        "voice": config.get('YandexCloud', 'voice', fallback='alyss'),
        "emotion": config.get('YandexCloud', 'emotion', fallback='neutral'),
        "speed": config.get('YandexCloud', 'speed', fallback='1.0'),
        "api_key": config.get('YandexCloud', 'api_key'),
        "folder_id": config.get('YandexCloud', 'folder_id')
    }
    
    return settings

class CustomHTTPRequestHandler(SimpleHTTPRequestHandler):
    """Кастомный HTTPRequestHandler для перенаправления логов в основной логгер."""

    def log_message(self, format, *args):
        """Переопределение метода логирования."""
        message = "%s - - [%s] %s\n" % (
            self.client_address[0],
            self.log_date_time_string(),
            format % args
        )
        logger.info(f"(HTTPServer) {message.strip()}")

class VoiceSynthesizer:
    def __init__(self, api_key, folder_id, http_host, http_port, audio_base_url):
        self.api_key = api_key
        self.folder_id = folder_id
        self.url = "https://tts.api.cloud.yandex.net/speech/v1/tts:synthesize"

        # Параметры HTTP-сервера
        self.http_host = http_host
        self.http_port = http_port
        self.audio_base_url = audio_base_url

        # Папка для хранения аудиосообщений локально
        self.base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), 'audio_sms', 'audio'))
        if not os.path.exists(self.base_dir):
            logger.error(f"Ошибка: Папка {self.base_dir} не найдена.")
        else:
            logger.info(f"Используем существующую директорию: {self.base_dir}")

        # Запуск HTTP-сервера в отдельном потоке
        self.start_http_server()

    def start_http_server(self):
        """Запуск встроенного HTTP-сервера для обслуживания аудиофайлов."""
        os.chdir(self.base_dir)
        handler = CustomHTTPRequestHandler
        self.httpd = HTTPServer((self.http_host, self.http_port), handler)
        logger.info(f"(HTTPServer) Запуск HTTP-сервера на {self.http_host}:{self.http_port}, обслуживаются файлы из {self.base_dir}")

        server_thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        server_thread.start()

    def synthesize(self, object_id, template_variables, message_template=None):
        """
        Генерация аудиосообщения с использованием Yandex.Cloud TTS API.

        :param object_id: Уникальный идентификатор объекта, используется как имя файла
        :param template_variables: Переменные для замены в шаблоне сообщения
        :param message_template: Шаблон сообщения для синтеза
        :return: URL к сгенерированным аудиофайлам или None в случае ошибки
        """
        # Загрузка текста из конфигурационного файла
        if not message_template:
            message_template = load_message_template()

        logger.info(f"Текст для синтеза: {message_template}")  # Проверка текста перед синтезом

        # Загрузка настроек синтеза речи из конфиг файла
        synthesizer_settings = load_synthesizer_settings()
        voice = synthesizer_settings["voice"]
        emotion = synthesizer_settings["emotion"]
        speed = synthesizer_settings["speed"]

        headers = {
            "Authorization": f"Api-Key {self.api_key}"
        }

        # Формируем текст сообщения
        try:
            message_text = message_template.format(**template_variables)
        except KeyError as e:
            logger.error(f"Ошибка форматирования шаблона сообщения: отсутствует ключ {e}")
            return None

        data = {
            "text": message_text,
            "lang": "ru-RU",
            "voice": voice,  # Голос из конфиг файла
            "speed": str(speed),  # Скорость из конфиг файла
            "emotion": emotion,  # Эмоция из конфиг файла
            "folderId": self.folder_id,
            "format": "oggopus",
            "sampleRateHertz": "48000"
        }

        # Путь для сохранения аудиофайлов локально
        ogg_filename = f"{object_id}.ogg"
        ogg_output = os.path.join(self.base_dir, ogg_filename)

        logger.info(f"Отправка запроса на синтез речи для объекта {object_id}...")

        try:
            response = requests.post(self.url, headers=headers, data=data, stream=True)
            response.raise_for_status()
        except requests.exceptions.RequestException as e:
            logger.error(f"Ошибка при выполнении запроса: {e}")
            return None

        # Сохраняем аудиофайл в формате OGG
        if response.status_code == 200:
            try:
                with open(ogg_output, "wb") as f:
                    for chunk in response.iter_content(chunk_size=4096):
                        if chunk:
                            f.write(chunk)
                logger.info(f"Файл {ogg_output} успешно создан.")

                # Конвертируем ogg в mp3 и wav
                mp3_filename = f"{object_id}.mp3"
                mp3_output = os.path.join(self.base_dir, mp3_filename)
                wav_filename = f"{object_id}.wav"
                wav_output = os.path.join(self.base_dir, wav_filename)

                try:
                    # Конвертация OGG -> MP3 и WAV
                    audio = AudioSegment.from_file(ogg_output)
                    audio.export(mp3_output, format="mp3")
                    audio.export(wav_output, format="wav")

                    logger.info(f"Файлы {mp3_output} и {wav_output} успешно созданы.")
                except Exception as e:
                    logger.error(f"Ошибка при конвертации аудиофайла: {e}")
                    return None

                # Формируем URL аудиофайлов
                audio_file_urls = {
                    'ogg': urljoin(self.audio_base_url, ogg_filename),
                    'mp3': urljoin(self.audio_base_url, mp3_filename),
                    'wav': urljoin(self.audio_base_url, wav_filename)
                }

                logger.info(f"URL аудиофайлов: {audio_file_urls}")

                # Очищаем старые файлы
                self.cleanup_old_files()

                return audio_file_urls
            except Exception as e:
                logger.error(f"Ошибка при сохранении файла: {e}")
                return None
        else:
            logger.error(f"Ошибка синтеза речи: {response.status_code} - {response.text}")
            return None

    def cleanup_old_files(self):
        """Удаляет старые файлы, оставляя только 30 последних."""
        files = [os.path.join(self.base_dir, f) for f in os.listdir(self.base_dir) if f.endswith(('.ogg', '.mp3', '.wav'))]
        files.sort(key=os.path.getmtime)

        if len(files) > 30:
            for file_to_delete in files[:-30]:
                try:
                    os.remove(file_to_delete)
                    logger.info(f"(HTTPServer) Удален старый файл: {file_to_delete}")
                except Exception as e:
                    logger.error(f"(HTTPServer) Ошибка удаления файла {file_to_delete}: {e}")

    def stop_http_server(self):
        """Останавливает HTTP-сервер."""
        if hasattr(self, 'httpd'):
            self.httpd.shutdown()
            logger.info("(HTTPServer) HTTP-сервер остановлен.")
