import requests
import configparser
import logging
import re
import os


logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger('sms_manager')

# Загрузка конфигурации из config.ini
config = configparser.ConfigParser()
config_path = os.path.join(os.path.dirname(__file__), 'config.ini')
config_loaded = False

try:
    if config.read(config_path, encoding='utf-8'):
        logger.info(f"Конфигурационный файл '{config_path}' успешно прочитан.")
    else:
        raise FileNotFoundError(f"Конфигурационный файл '{config_path}' не найден или пуст.")

    # Проверка наличия раздела 'SMS'
    if 'SMS' not in config:
        raise KeyError("Раздел 'SMS' отсутствует в config.ini. Пожалуйста, добавьте его.")

    # Получаем параметры из конфигурации
    api_url = config['SMS'].get('url', 'https://bsms.tele2.ru/api/send')
    login = config['SMS'].get('login', '')
    password = config['SMS'].get('password', '')
    shortcode = config['SMS'].get('shortcode', 'ZD_ohrana')

    # Проверяем, что все необходимые параметры присутствуют
    if not all([api_url, login, password, shortcode]):
        raise ValueError("Некоторые параметры раздела 'SMS' отсутствуют в config.ini.")

    config_loaded = True

except Exception as e:
    logger.info(f"Ошибка при загрузке конфигурации: {e}")
    config_loaded = False

def is_valid_phone_number(phone_number):
    """Проверяет корректность формата номера телефона."""
    pattern = re.compile(r'^\d{6}$|^\d{11}$')  # Принимаются номера из 6 или 11 цифр
    return bool(pattern.match(phone_number))

def send_http_sms(phone_number, message, url, login, password, shortcode):
    """Функция для отправки SMS через HTTP API."""
    if not config_loaded:
        logger.info("Ошибка: Параметры конфигурации не загружены. Отправка SMS невозможна.")
        return False

    if not is_valid_phone_number(phone_number):
        logger.info(f"Ошибка: Некорректный формат номера телефона: {phone_number}")
        return False

    # Параметры для отправки SMS
    params = {
        'operation': 'send',
        'login': login,
        'password': password,
        'msisdn': phone_number,
        'text': message
    }

    try:
        # Выполняем GET-запрос с параметрами
        response = requests.get(url, params=params, timeout=10, verify=False)

        # Логирование запроса и ответа для отладки
        logger.info(f"Отправлен запрос: {response.url}")
        logger.info(f"Ответ сервера: {response.text}")

        # Проверка успешного ответа
        if response.status_code == 200:
            response_text = response.text.strip()
            if 'ERROR' in response_text:
                logger.info(f"Ошибка при отправке SMS: {response_text}")
                return False
            else:
                logger.info(f"Сообщение успешно отправлено на номер {phone_number}. Ответ сервера: {response_text}")
                return True
        else:
            logger.info(f"Ошибка отправки сообщения. Код ответа: {response.status_code}. Текст ответа: {response.text}")
            return False

    except requests.RequestException as e:
        logger.info(f"Ошибка при соединении с сервером SMS: {e}")
        return False
