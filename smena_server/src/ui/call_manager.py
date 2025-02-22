# call_manager.py
import os
import logging
import time
import threading
import requests
from requests.auth import HTTPDigestAuth
from asterisk.ami import AMIClient
from datetime import datetime

# Создадим логгер call_manager
logger = logging.getLogger('call_manager')

# Создадим отдельный логгер для сырых AMI-событий
ami_logger = logging.getLogger('ami_events')

# Определим путь к logs/ami_log.log
script_dir = os.path.dirname(os.path.abspath(__file__))
logs_dir = os.path.join(script_dir, 'logs')
if not os.path.exists(logs_dir):
    os.makedirs(logs_dir)
ami_log_path = os.path.join(logs_dir, 'ami_log.log')

# Настраиваем FileHandler для ami_logger
ami_file_handler = logging.FileHandler(ami_log_path, mode='a', encoding='utf-8')
ami_file_handler.setLevel(logging.INFO)
ami_file_handler.setFormatter(logging.Formatter('%(asctime)s - %(message)s'))
ami_logger.addHandler(ami_file_handler)
ami_logger.propagate = False


class CallManager:
    """
    CallManager отвечает за:
    1. Подключение к AMI (проверяет наличие связи).
    2. Инициирует звонок (make_call) через HTTP (ARawman), возвращает ActionID.
    3. Слушает события AMI (_on_ami_event) и сопоставляет их с ActionID.
    4. При получении финального статуса звонка вызывает callback(action_id, status, call_info).
    """

    def __init__(self, config, callback):
        """
        :param config: ConfigParser/словарь с настройками Asterisk и HTTP.
        :param callback: функция-обработчик статусов звонков: callback(action_id, status, call_info).
        """
        self.config = config
        self.callback = callback

        # Настройки AMI
        self.ami_host = config['Asterisk'].get('host', '127.0.0.1')
        self.ami_port = config['Asterisk'].getint('port', 5038)
        self.ami_username = config['Asterisk'].get('user', 'admin')
        self.ami_password = config['Asterisk'].get('password', 'password')

        # Настройки HTTP (ARawman)
        self.http_host = config['AsteriskHTTP'].get('host', '127.0.0.1')
        self.http_port = config['AsteriskHTTP'].getint('port', 8088)
        self.http_username = config['AsteriskHTTP'].get('user', 'admin')
        self.http_password = config['AsteriskHTTP'].get('password', 'password')
        self.base_url = f"http://{self.http_host}:{self.http_port}/asterisk/arawman"

        # Активные звонки: action_id -> {'phone_number':..., 'panel_id':..., ...}
        self.active_calls = {}

        # Подключение к AMI
        self._stop = threading.Event()
        self.client = AMIClient(address=self.ami_host, port=self.ami_port)
        try:
            self.client.connect()
            self.client.login(username=self.ami_username, secret=self.ami_password)
            logger.info("CallManager: Подключение к AMI выполнено")
        except Exception as e:
            logger.error(f"CallManager: Не удалось подключиться к AMI: {e}")

        # Слушаем все события
        self.client.add_event_listener(self._on_ami_event)

    def _on_ami_event(self, event, **kwargs):
        """
        Сюда приходят все события AMI.
        Логируем их в ami_log.log (через ami_logger).
        Пытаемся извлечь финальный статус для известных нам ActionID.
        """
        ami_logger.info("Событие: %s, данные: %s", event.name, event)

        name = event.name
        data = event.keys

        if name == 'OriginateResponse' and 'ActionID' in data:
            action_id = data.get('ActionID')
            if action_id in self.active_calls:
                response = data.get('Response', '')
                reason = data.get('Reason', '')
                final_status = self.map_originate_response(response, reason)
                self.fire_callback_if_final(action_id, final_status)

        elif name == 'DialEnd' and 'DialStatus' in data:
            # Можем дополнительно обрабатывать, если нужно
            pass
        elif name == 'Hangup' and 'Cause' in data:
            # Аналогично, если нужно
            pass

    def map_originate_response(self, response, reason):
        """
        Преобразует (Response, Reason) в финальный статус.
        Пример:
          - response='Success' + reason=4 => ANSWERED
          - response='Failure' => FAILED
          - reason=5 => BUSY
          ...
        """
        if response.lower() == 'failure':
            return 'FAILED'
        if response.lower() == 'success':
            if reason == '4':
                return 'ANSWERED'
            elif reason == '5':
                return 'BUSY'
            else:
                return 'NO ANSWER'
        return None

    def fire_callback_if_final(self, action_id, final_status):
        """
        Если final_status не None, вызываем self.callback(action_id, final_status, call_info)
        и удаляем звонок из self.active_calls.
        """
        if final_status is not None:
            call_info = self.active_calls.get(action_id, {})
            self.callback(action_id, final_status, call_info)
            self.active_calls.pop(action_id, None)

    def make_call(self, phone_number, file_name, panel_id=None):
        """
        Инициирует звонок через HTTP-запрос. Возвращает action_id.
        """
        action_id = f"originate-{int(time.time() * 1000)}"
        variables = {"phone_number": phone_number, "vfile": file_name}
        if panel_id:
            variables["panel_id"] = panel_id

        params = {
            'action': 'Originate',
            'Channel': f'Local/{phone_number}@out-bot1',
            'Context': 'out-bot',
            'Exten': 'bot',
            'Priority': 1,
            'Account': 'VOICEBOT',
            'Async': 'true',
            'ActionID': action_id,
            'Variable': ','.join(f"{k}={v}" for k, v in variables.items()),
        }

        logger.info(f"[make_call] action_id={action_id}, параметры: {params}")
        try:
            r = requests.get(
                self.base_url,
                params=params,
                auth=HTTPDigestAuth(self.http_username, self.http_password),
                timeout=5
            )
            if r.status_code == 200:
                logger.info(f"Originate => успешно: {r.text.strip()}")
            else:
                logger.error(f"Originate => ошибка {r.status_code}: {r.text}")
        except Exception as e:
            logger.error(f"Исключение в make_call: {e}")

        self.active_calls[action_id] = {
            'phone_number': phone_number,
            'panel_id': panel_id,
            'file_name': file_name,
            'start_time': datetime.now()
        }
        return action_id

    def stop(self):
        self._stop.set()
        try:
            self.client.logoff()
            logger.info("CallManager: Отсоединение от AMI выполнено")
        except Exception as ex:
            logger.error(f"Ошибка при отключении от AMI: {ex}")
        logger.info("CallManager остановлен.")
