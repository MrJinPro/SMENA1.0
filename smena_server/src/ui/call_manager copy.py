import logging
import time
import threading
import requests
from requests.auth import HTTPDigestAuth
from asterisk.ami import AMIClient, SimpleAction

# Настройка логирования
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger('call_manager')

# Настройка отдельного файла для логов AMI событий
ami_logger = logging.getLogger('ami_events')
ami_handler = logging.FileHandler('ami_log.log', mode='w', encoding='utf-8')  # Указана кодировка UTF-8
ami_handler.setLevel(logging.INFO)
ami_formatter = logging.Formatter('%(asctime)s - %(message)s')
ami_handler.setFormatter(ami_formatter)
ami_logger.addHandler(ami_handler)
ami_logger.propagate = False

class CallManager:
    def __init__(self, config, callback):
        self.config = config
        self.callback = callback

        # Настройки подключения к AMI
        self.ami_host = config['Asterisk'].get('host', '192.168.3.20')
        self.ami_port = config.getint('Asterisk', 'port', fallback=5038)
        self.ami_username = config['Asterisk'].get('user')
        self.ami_password = config['Asterisk'].get('password')

        # Настройки HTTP для инициирования звонков
        self.http_host = config['AsteriskHTTP'].get('host', '192.168.3.20')
        self.http_port = config.getint('AsteriskHTTP', 'port', fallback=8088)
        self.http_username = config['AsteriskHTTP'].get('user')
        self.http_password = config['AsteriskHTTP'].get('password')

        # URL для HTTP-запросов
        self.base_url = f"http://{self.http_host}:{self.http_port}/asterisk/arawman"

        # Инициализация AMI клиента
        self.client = AMIClient(address=self.ami_host, port=self.ami_port)
        try:
            self.client.login(username=self.ami_username, secret=self.ami_password)
            logger.info("Успешно подключились к AMI")
        except Exception as e:
            logger.error(f"Ошибка подключения к AMI: {e}")
            raise e

        # Регистрация обработчика событий
        self.client.add_event_listener(self.handle_event)

        # Активные вызовы
        self.active_calls = {}  # {phone_number: {file_name, panel_id, uniqueid}}
        self.lock = threading.Lock()

    def handle_event(self, event, **kwargs):
        event_name = event.name
        ami_logger.info(f"Событие: {event_name}, данные: {event}")

        if event_name == 'DialEnd':
            self.handle_dial_end(event)
        elif event_name == 'OriginateResponse':
            self.handle_originate_response(event)
        elif event_name == 'Hangup':
            self.handle_hangup(event)

    def handle_originate_response(self, event):
        response = event.get('Response')
        channel = event.get('Channel')
        logger.info(f"OriginateResponse: Channel={channel}, Response={response}")

        if response.lower() != 'success':
            logger.warning(f"Ошибка инициирования звонка: Channel={channel}, Response={response}")

    def handle_dial_end(self, event):
        dial_status = event.get('DialStatus')
        dest_channel = event.get('DestChannel')
        phone_number = self.extract_phone_number(dest_channel)

        logger.info(f"DialEnd: PhoneNumber={phone_number}, DialStatus={dial_status}")

        with self.lock:
            call_data = self.active_calls.pop(phone_number, None)

        if call_data:
            self.callback(phone_number, 'CALL_COMPLETED', call_data, {'dial_status': dial_status})
        else:
            logger.warning(f"DialEnd для номера {phone_number} не найдено в активных вызовах")

    def handle_hangup(self, event):
        uniqueid = event.get('Uniqueid')
        cause = event.get('Cause')
        channel = event.get('Channel')
        phone_number = self.extract_phone_number(channel)

        logger.info(f"Hangup: PhoneNumber={phone_number}, Cause={cause}, UniqueID={uniqueid}")

        with self.lock:
            call_data = self.active_calls.pop(phone_number, None)

        if call_data:
            self.callback(phone_number, 'CALL_HANGUP', call_data, {'uniqueid': uniqueid, 'cause': cause})
        else:
            logger.warning(f"Hangup для номера {phone_number} не найдено в активных вызовах")

    def make_call(self, phone_number, file_name, panel_id=None):
        action_id = f"originate-{int(time.time() * 1000)}"
        variables = {
            'vfile': file_name,
            'action_id': action_id,
        }
        if panel_id:
            variables['panel_id'] = panel_id

        params = {
            'action': 'Originate',
            'Channel': f'Local/{phone_number}@out-bot1',
            'Context': 'out-bot',
            'Exten': 'bot',
            'Priority': 1,
            'Account': 'VOICEBOT',
            'Async': 'true',
            'ActionID': action_id,
            'Variable': ','.join(f"{key}={value}" for key, value in variables.items())
        }

        logger.info(f"Отправка HTTP-запроса для звонка: {params}")
        try:
            response = requests.get(
                self.base_url,
                params=params,
                auth=HTTPDigestAuth(self.http_username, self.http_password),
                timeout=10
            )
            if response.status_code == 200:
                logger.info(f"Звонок успешно инициирован: {response.text}")
                with self.lock:
                    self.active_calls[phone_number] = {
                        'file_name': file_name,
                        'panel_id': panel_id,
                        'uniqueid': None
                    }
                return action_id
            else:
                logger.error(f"Ошибка HTTP-запроса: {response.status_code}, {response.text}")
        except Exception as e:
            logger.error(f"Ошибка при выполнении HTTP-запроса: {e}")
        return None

    def extract_phone_number(self, channel):
        if channel and '/' in channel:
            try:
                return channel.split('/')[1].split('@')[0]
            except IndexError:
                return None
        return None

    def stop(self):
        try:
            self.client.logoff()
            logger.info("Отключение от AMI")
        except Exception as e:
            logger.error(f"Ошибка отключения от AMI: {e}")
