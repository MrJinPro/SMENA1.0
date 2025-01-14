import logging
import os
import time
import threading
import requests
from requests.auth import HTTPDigestAuth
from asterisk.ami import AMIClient

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger('call_manager')

# Лог AMI-событий
ami_logger = logging.getLogger('ami_events')
ami_handler = logging.FileHandler('ami_log.log', mode='a', encoding='utf-8')
ami_handler.setLevel(logging.INFO)
ami_formatter = logging.Formatter('%(asctime)s - %(message)s')
ami_logger.addHandler(ami_handler)
ami_logger.propagate = False


class CallTracker:
    def __init__(self, callback):
        self.calls = {}  # linkedid -> {'uniqueids': [...], 'info': {...}}
        self.lock = threading.Lock()
        self.callback = callback

    def add_call(self, uniqueid, linkedid, panel_id, phone_number):
        with self.lock:
            if linkedid not in self.calls:
                self.calls[linkedid] = {
                    'uniqueids': [],
                    'info': {
                        'panel_id': panel_id,
                        'phone_number': phone_number,
                        'start_time': time.time(),
                        'status': 'INIT'
                    }
                }
            if uniqueid not in self.calls[linkedid]['uniqueids']:
                self.calls[linkedid]['uniqueids'].append(uniqueid)
            logger.info(f"CallTracker: add_call linkedid={linkedid}, uniqueid={uniqueid}")

    def update_status(self, uniqueid, linkedid, status, extra_info=None):
        with self.lock:
            if linkedid not in self.calls:
                logger.warning(f"CallTracker: неизвестный linkedid={linkedid}, status={status}")
                return

            if uniqueid not in self.calls[linkedid]['uniqueids']:
                self.calls[linkedid]['uniqueids'].append(uniqueid)

            self.calls[linkedid]['info']['status'] = status
            if status in ['ANSWERED', 'NO ANSWER', 'BUSY', 'FAILED', 'CANCELED', 'HUNG_UP']:
                self.calls[linkedid]['info']['end_time'] = time.time()

            call_info = self.calls[linkedid]['info'].copy()

        self.callback(linkedid, uniqueid, status, call_info, extra_info)

    def remove_call(self, linkedid):
        with self.lock:
            if linkedid in self.calls:
                del self.calls[linkedid]
                logger.info(f"CallTracker: remove_call linkedid={linkedid}")
            else:
                logger.warning(f"CallTracker: remove_call нет в списке linkedid={linkedid}")


class CallManager:
    def __init__(self, config, callback):
        self.config = config
        self.callback = callback

        self.ami_host = config['Asterisk'].get('host', '192.168.3.20')
        self.ami_port = config['Asterisk'].getint('port', fallback=5038)
        self.ami_user = config['Asterisk'].get('user')
        self.ami_pass = config['Asterisk'].get('password')

        self.http_host = config['AsteriskHTTP'].get('host', '192.168.3.20')
        self.http_port = config['AsteriskHTTP'].getint('port', fallback=8088)
        self.http_user = config['AsteriskHTTP'].get('user')
        self.http_secret = config['AsteriskHTTP'].get('password')
        self.base_url = f"http://{self.http_host}:{self.http_port}/asterisk/arawman"

        # Подключаемся к AMI
        self.client = AMIClient(address=self.ami_host, port=self.ami_port)
        try:
            self.client.connect()
            self.client.login(username=self.ami_user, secret=self.ami_pass)
            logger.info("Подключение к AMI успешно")
        except Exception as e:
            logger.error(f"Ошибка подключения к AMI: {e}")
            raise

        self.call_tracker = CallTracker(self.on_tracker_event)

        # Слушаем все события
        self.client.add_event_listener(self.on_ami_event)

        # Фоновый парсер лога
        self.stop_flag = threading.Event()
        self.parser_thread = threading.Thread(target=self.parse_ami_log, daemon=True)
        self.parser_thread.start()

    def on_ami_event(self, event, **kwargs):
        ami_logger.info(f"Event: {event.name}, data: {dict(event)}")
        e_name = event.name
        uniqueid = event.get('Uniqueid')
        linkedid = event.get('Linkedid')
        if not uniqueid and not linkedid:
            return

        if e_name in ['Newstate']:
            st = event.get('ChannelStateDesc', '').lower()
            if st == 'ring':
                self.call_tracker.update_status(uniqueid, linkedid, 'RINGING')
            elif st == 'up':
                self.call_tracker.update_status(uniqueid, linkedid, 'ANSWERED')
            elif st == 'down':
                self.call_tracker.update_status(uniqueid, linkedid, 'HUNG_UP')

        elif e_name in ['Dial', 'DialBegin']:
            dial_status = event.get('DialStatus', 'UNKNOWN').upper()
            self.call_tracker.update_status(uniqueid, linkedid, dial_status)

        elif e_name in ['DialEnd']:
            dial_status = event.get('DialStatus', 'UNKNOWN').upper()
            self.call_tracker.update_status(uniqueid, linkedid, dial_status)

        elif e_name == 'Hangup':
            cause = event.get('Cause-txt', '')
            self.call_tracker.update_status(uniqueid, linkedid, 'HUNG_UP', {'cause': cause})

        elif e_name == 'OriginateResponse':
            resp = event.get('Response', '')
            if resp.lower() != 'success':
                self.call_tracker.update_status(uniqueid, linkedid, 'FAILED', {'response': resp})

    def on_tracker_event(self, linkedid, uniqueid, status, call_info, extra_info):
        panel_id = call_info.get('panel_id')
        phone_number = call_info.get('phone_number')

        # Формируем report_data
        report_data = {
            'ID объекта': panel_id,
            'ID события': uniqueid,
            'Номер телефона': phone_number,
            'Статус': f"Звонок завершен: {status}",
            'Дата и время обработки': time.strftime('%Y-%m-%d %H:%M:%S'),
            'Время события': time.strftime('%Y-%m-%d %H:%M:%S')
        }

        if status in ['ANSWERED', 'BRIDGED']:
            report_data['Статус'] = 'Звонок принят'
            self.callback(linkedid, 'CALL_COMPLETED', report_data, extra_info)
            self.call_tracker.remove_call(linkedid)
        elif status in ['NO ANSWER', 'BUSY', 'FAILED', 'CANCELED', 'HUNG_UP']:
            self.callback(linkedid, 'CALL_HANGUP', report_data, extra_info)
            self.call_tracker.remove_call(linkedid)

    def make_call(self, phone_number, file_name, panel_id=None):
        action_id = f"orig-{int(time.time()*1000)}"
        variables = {
            'vfile': file_name,
            'phone_number': phone_number
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
            'Variable': ','.join(f"{k}={v}" for k,v in variables.items())
        }

        logger.info(f"[HTTP-Originate] -> {params}")
        try:
            r = requests.get(
                self.base_url,
                params=params,
                auth=HTTPDigestAuth(self.http_user, self.http_secret),
                timeout=10
            )
            if r.status_code == 200 and 'Success' in r.text:
                logger.info(f"Успешная инициализация: {r.text.strip()}")
                self.call_tracker.add_call(action_id, action_id, panel_id, phone_number)
                return action_id
            else:
                logger.error(f"Ошибка HTTP Originate: {r.status_code}, {r.text}")
        except Exception as e:
            logger.error(f"Исключение при HTTP Originate: {e}")
        return None

    def parse_ami_log(self):
        log_file = 'ami_log.log'
        while not self.stop_flag.is_set():
            try:
                if os.path.exists(log_file):
                    with open(log_file, 'r', encoding='utf-8') as f:
                        _ = f.readlines()
                time.sleep(5)
            except:
                time.sleep(5)

    def stop(self):
        logger.info("CallManager -> stop()")
        self.stop_flag.set()
        self.parser_thread.join()
        try:
            self.client.logoff()
        except:
            pass
        logger.info("CallManager остановлен.")
