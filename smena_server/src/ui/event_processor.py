# event_processor.py
import os
import re
import csv
import time
import socket
import queue
import logging
import threading
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor

from PyQt5.QtCore import QObject, pyqtSignal
from ui.voice_synthesizer import VoiceSynthesizer
from ui.call_manager import CallManager
from ui.sms_manager import send_http_sms
from ui.utils import number_to_spelled_digits
from db_connector import DBConnector


class EventProcessor(QObject):
    processing_started = pyqtSignal()
    processing_stopped = pyqtSignal()
    alarm_processed = pyqtSignal(str)

    def __init__(self, config, db_connector, parent=None):
        super().__init__(parent)
        self.config = config
        self.parent = parent
        self.db_connector = db_connector

        # Логгер event_processor
        self.logger = logging.getLogger('event_processor')
        self.logger.setLevel(logging.DEBUG)
        handler = logging.StreamHandler()
        formatter = logging.Formatter('%(asctime)s - event_processor - %(levelname)s - %(message)s')
        handler.setFormatter(formatter)
        if not self.logger.handlers:
            self.logger.addHandler(handler)

        # Инициализация общих блокировок и путей отчёта до загрузки конфигурации
        script_dir = os.path.dirname(os.path.abspath(__file__))
        self.report_dir = os.path.join(script_dir, 'otcet')
        os.makedirs(self.report_dir, exist_ok=True)
        self.report_lock = threading.Lock()
        self.report_file_path = os.path.join(self.report_dir, datetime.now().strftime('%Y.%m.01') + '.csv')
        self.initialize_report_file()
        self.initialize_detailed_report()

        # Создаём блокировку для синхронизации доступа к action_id_to_call_info
        self.action_id_to_call_info = {}
        self.action_id_lock = threading.Lock()

        # Загрузка параметров
        self.load_config_parameters()

        # Инициализация компонентов
        self.synthesizer = VoiceSynthesizer(
            api_key=self.config['YandexCloud']['api_key'],
            folder_id=self.config['YandexCloud']['folder_id'],
            http_host=self.config['HTTPServer']['host'],
            http_port=int(self.config['HTTPServer']['port']),
            audio_base_url=self.config['HTTPServer']['base_url']
        )
        self.call_manager = CallManager(config=self.config, callback=self.handle_call_event)

        # Настройки SMS
        self.sms_url = self.config['SMS']['url']
        self.sms_login = self.config['SMS']['login']
        self.sms_password = self.config['SMS']['password']
        self.sms_shortcode = self.config['SMS']['shortcode']

        # Очередь и пул потоков
        self.event_queue = queue.Queue()
        self.max_concurrent_events = int(self.config.get('EventProcessing', 'max_concurrent_events', fallback='5'))
        self.executor = ThreadPoolExecutor(max_workers=self.max_concurrent_events)
        self.futures = set()
        self.processing_enabled = False

        # Отслеживание времени последней обработки объектов
        self.active_events = {}
        self.lock = threading.Lock()

        # Привязка ActionID -> call_info уже выполнена выше через action_id_to_call_info

        # Список ответственных и индекс текущей попытки
        self.event_responsibles = {}
        self.event_call_attempts = {}

        self.call_delay_seconds = int(self.config.get('EventProcessing', 'call_delay_seconds', fallback='180'))

        # Настраиваем пути к логам AMI
        self.logs_dir = os.path.join(script_dir, 'logs')
        os.makedirs(self.logs_dir, exist_ok=True)
        self.ami_log_path = self.config.get('Log', 'ami_log_path', fallback=os.path.join(self.logs_dir, 'ami_log.log'))
        self.status_ami_log_path = os.path.join(self.logs_dir, '_status_ami_log.log')

        self.ami_parser_thread = None
        self.logger.debug("EventProcessor инициализирован.")
        self.write_detailed_report("EventProcessor инициализирован.")

    def initialize_detailed_report(self):
        self.detailed_report_file_path = os.path.join(self.report_dir, 'detailed_report.log')
        with open(self.detailed_report_file_path, 'w', encoding='utf-8') as f:
            f.write("Детальный отчёт работы EventProcessor\n")

    def write_detailed_report(self, message):
        with self.report_lock:
            with open(self.detailed_report_file_path, 'a', encoding='utf-8') as f:
                f.write(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} - {message}\n")

    def load_config_parameters(self):
        self.repeat_interval = timedelta(seconds=int(self.config.get('EventProcessing', 'repeat_interval', fallback='30')))
        self.event_codes = self.load_event_codes_from_config()
        self.test_mode = self.config.getboolean('Testing', 'test_mode', fallback=False)
        self.test_phone_number = self.config.get('Testing', 'test_phone_number', fallback='')
        self.sms_template = self.config.get('Message', 'sms_text', fallback='')
        self.tts_template = self.config.get('Message', 'tts_text', fallback='')
        self.use_ssml = self.config.getboolean('Message', 'use_ssml', fallback=False)
        self.call_timeout = int(self.config.get('EventProcessing', 'call_timeout', fallback='60'))
        self.max_call_attempts = int(self.config.get('EventProcessing', 'max_call_attempts', fallback='3'))
        self.write_detailed_report("Параметры конфигурации загружены.")

    def load_event_codes_from_config(self):
        codes_str = self.config.get('EventCodes', 'codes', fallback='')
        return [code.strip() for code in codes_str.split(',') if code.strip()]

    def initialize_report_file(self):
        with self.report_lock:
            if not os.path.exists(self.report_file_path):
                with open(self.report_file_path, 'w', newline='', encoding='utf-8') as csvfile:
                    fieldnames = [
                        'Дата и время обработки', 'ID объекта', 'ID события', 'Код события',
                        'Время события', 'Адрес', 'Название компании', 'Ответственный',
                        'Номер телефона', 'Статус', 'Дополнительная информация'
                    ]
                    writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
                    writer.writeheader()

    def write_to_report(self, data):
        with self.report_lock:
            current_report_path = os.path.join(
                self.report_dir,
                datetime.now().strftime('%Y.%m.01') + '.csv'
            )
            if current_report_path != self.report_file_path:
                self.report_file_path = current_report_path
                self.initialize_report_file()
            with open(self.report_file_path, 'a', newline='', encoding='utf-8') as csvfile:
                fieldnames = [
                    'Дата и время обработки', 'ID объекта', 'ID события', 'Код события',
                    'Время события', 'Адрес', 'Название компании', 'Ответственный',
                    'Номер телефона', 'Статус', 'Дополнительная информация'
                ]
                writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
                writer.writerow(data)
        self.write_detailed_report(f"Запись в отчёт: {data}")

    def start_processing(self):
        if not self.processing_enabled:
            self.processing_enabled = True
            self.logger.info("Обработка событий запущена.")
            self.write_detailed_report("Обработка событий запущена.")
            self.processing_started.emit()

            self.processing_thread = threading.Thread(
                target=self.event_processing_loop,
                daemon=True
            )
            self.processing_thread.start()

            # Запуск парсера AMI лога
            self.start_ami_log_parser()
        else:
            self.logger.info("Обработка событий уже запущена.")
            self.write_detailed_report("Попытка запуска: обработка событий уже запущена.")

    def start_ami_log_parser(self):
        self.logger.debug("Запуск парсера AMI лога в отдельном потоке...")
        self.write_detailed_report("Запуск парсера AMI лога в отдельном потоке.")
        self.ami_parser_thread = threading.Thread(target=self.ami_log_parser_loop, daemon=True)
        self.ami_parser_thread.start()

    def ami_log_parser_loop(self):
        try:
            with open(self.ami_log_path, 'r', encoding='utf-8') as src, \
                 open(self.status_ami_log_path, 'a', encoding='utf-8') as dst:
                src.seek(0, 2)
                while self.processing_enabled:
                    line = src.readline()
                    if not line:
                        time.sleep(1)
                        continue

                    # Получаем копию action_id_to_call_info с блокировкой
                    with self.action_id_lock:
                        current_actions = list(self.action_id_to_call_info.items())
                    
                    for action_id, call_info in current_actions:
                        if action_id in line:
                            dst.write(line)
                            dst.flush()
                            found_status = self.extract_status_from_line(line)
                            if found_status:
                                self.handle_call_event(
                                    uniqueid=action_id,
                                    status=found_status,
                                    call_info=call_info
                                )
                                self.write_detailed_report(f"AMI лог: найден ActionID {action_id} со статусом {found_status}.")
        except Exception as e:
            self.logger.error(f"Ошибка в ami_log_parser_loop: {e}")
            self.write_detailed_report(f"Ошибка в ami_log_parser_loop: {e}")

    def extract_status_from_line(self, line):
        dial_end_match = re.search(r"DialEnd.*'DialStatus':\s*'([^']+)'", line)
        if dial_end_match:
            return self.normalize_dialstatus(dial_end_match.group(1))

        dialstatus_match = re.search(r"'DialStatus':\s*'([^']+)'", line)
        if dialstatus_match:
            return self.normalize_dialstatus(dialstatus_match.group(1))

        orig_resp = re.search(r"OriginateResponse.*'Response':\s*'([^']+)'", line)
        if orig_resp:
            response = orig_resp.group(1).lower()
            return 'BRIDGED' if response == 'success' else 'FAILED'

        return None

    def normalize_dialstatus(self, raw_status):
        dial_map = {
            'ANSWER': 'ANSWERED',
            'BUSY': 'BUSY',
            'NOANSWER': 'NO ANSWER',
            'NO ANSWER': 'NO ANSWER',
            'FAILED': 'FAILED',
            'CANCEL': 'CANCELED',
            'CANCELED': 'CANCELED',
            'ANSWERED': 'ANSWERED',
            'BRIDGED': 'BRIDGED'
        }
        return dial_map.get(raw_status.upper(), raw_status.upper())

    def stop_processing(self):
        if self.processing_enabled:
            self.processing_enabled = False
            self.logger.info("Обработка событий остановлена.")
            self.write_detailed_report("Обработка событий остановлена.")
            self.processing_stopped.emit()
            self.executor.shutdown(wait=True)
            self.futures.clear()
            with self.event_queue.mutex:
                self.event_queue.queue.clear()
            self.logger.debug("Все рабочие потоки остановлены.")
            self.write_detailed_report("Все рабочие потоки остановлены.")
        else:
            self.logger.info("Обработка событий уже остановлена.")
            self.write_detailed_report("Попытка остановки: обработка событий уже остановлена.")

    def is_processing_active(self):
        return self.processing_enabled

    def enqueue_event(self, event):
        self.event_queue.put(event)
        if 'event_id' in event:
            self.logger.debug(f"Событие {event['event_id']} добавлено в очередь.")
            self.write_detailed_report(f"Событие {event['event_id']} добавлено в очередь.")

    def event_processing_loop(self):
        self.logger.debug("Начало цикла обработки событий.")
        self.write_detailed_report("Начало цикла обработки событий.")
        while self.processing_enabled:
            self.logger.debug("Загрузка событий из базы данных.")
            self.write_detailed_report("Загрузка событий из базы данных.")
            events = self.load_events_from_database()
            for event in events:
                if not self.processing_enabled:
                    break
                self.enqueue_event(event)
                self.try_process_events()
            self.logger.debug(f"Цикл завершен. Ждем {self.repeat_interval.total_seconds()} сек.")
            self.write_detailed_report(f"Цикл завершен. Ждем {self.repeat_interval.total_seconds()} сек.")
            time.sleep(self.repeat_interval.total_seconds())
        self.logger.debug("Цикл обработки событий завершен.")
        self.write_detailed_report("Цикл обработки событий завершен.")

    def try_process_events(self):
        while self.processing_enabled and not self.event_queue.empty() and len(self.futures) < self.max_concurrent_events:
            event = self.event_queue.get()
            future = self.executor.submit(self.process_event, event)
            self.futures.add(future)
            future.add_done_callback(self.futures.discard)
            self.logger.debug(f"Обработка события {event['event_id']} начата.")
            self.write_detailed_report(f"Обработка события {event['event_id']} начата.")

    def load_events_from_database(self):
        if not self.event_codes:
            self.logger.warning("Список кодов событий пуст.")
            self.write_detailed_report("Список кодов событий пуст.")
            return []
        database_name = self.config.get('Database', 'database', fallback='Pult4DB')
        placeholders = ', '.join(['%s'] * len(self.event_codes))
        query = f"""
        SELECT a.Panel_id, a.Event_id, a.Code, a.TimeEvent, 
               COALESCE(d.address, '') as address, 
               d.CompanyName,
               a.StateEvent
        FROM {database_name}.dbo.Temp a
        LEFT JOIN {database_name}.dbo.Panel b ON a.Panel_id = b.Panel_id
        LEFT JOIN {database_name}.dbo.Groups c ON c.Panel_id = b.Panel_id
        LEFT JOIN {database_name}.dbo.Company d ON d.ID = c.CompanyID
        WHERE a.Code IN ({placeholders}) AND a.StateEvent = 0
        """
        try:
            rows = self.db_connector.fetchall(query, self.event_codes)
            events = []
            for row in rows:
                events.append({
                    'panel_id': row['Panel_id'],
                    'event_id': row['Event_id'],
                    'code': row['Code'],
                    'time_event': row['TimeEvent'],
                    'address': row['address'],
                    'company_name': row['CompanyName'],
                    'state_event': row['StateEvent']
                })
            self.logger.debug(f"Загружено {len(events)} событий.")
            self.write_detailed_report(f"Загружено {len(events)} событий из БД.")
            return events
        except Exception as e:
            self.logger.error(f"Ошибка при загрузке событий: {e}")
            self.write_detailed_report(f"Ошибка при загрузке событий: {e}")
            return []

    def process_event(self, event):
        self.logger.debug(f"Начата обработка события {event['event_id']}.")
        self.write_detailed_report(f"Начата обработка события {event['event_id']}.")
        if not self.processing_enabled:
            self.logger.info("Обработка событий отключена.")
            self.write_detailed_report("Обработка событий отключена.")
            return
        panel_id = event.get('panel_id')
        event_id = event.get('event_id')
        if not self.can_process_event(panel_id):
            self.logger.info(f"Событие для объекта {panel_id} пропущено (не наступил нужный период).")
            self.write_detailed_report(f"Событие для объекта {panel_id} пропущено (не наступил нужный период).")
            return

        self.update_event_status(panel_id, event_id, state_event=1)
        with self.lock:
            self.active_events[panel_id] = datetime.now()

        self.handle_event_logic(event)

    def can_process_event(self, panel_id):
        now = datetime.now()
        with self.lock:
            last_time = self.active_events.get(panel_id, None)
        if last_time is None:
            return True
        if now.date() == last_time.date():
            self.logger.debug(f"Object {panel_id} уже обрабатывался сегодня. Пропускаем.")
            self.write_detailed_report(f"Object {panel_id} уже обрабатывался сегодня. Пропускаем.")
            return False
        hours_diff = (now - last_time).total_seconds() / 3600.0
        if hours_diff < 4.0:
            self.logger.debug(f"Object {panel_id} обрабатывался {hours_diff:.1f} ч назад (меньше 4). Пропускаем.")
            self.write_detailed_report(f"Object {panel_id} обрабатывался {hours_diff:.1f} ч назад (меньше 4). Пропускаем.")
            return False
        return True

    def update_event_status(self, panel_id, event_id, state_event):
        update_sql = """
        UPDATE dbo.Temp SET StateEvent = %s 
        WHERE Panel_id = %s AND Event_id = %s
        """
        try:
            rows_affected = self.db_connector.execute(update_sql, (state_event, panel_id, event_id))
            if state_event == 1:
                self.db_connector.commit()
            if rows_affected > 0:
                self.logger.debug(f"Статус события {event_id} -> {state_event}.")
                self.write_detailed_report(f"Статус события {event_id} обновлен на {state_event}.")
            else:
                self.logger.warning(f"Статус события {event_id} не обновлен (нет затронутых строк).")
                self.write_detailed_report(f"Статус события {event_id} не обновлен (нет затронутых строк).")
        except Exception as e:
            self.logger.error(f"Ошибка при обновлении статуса: {e}")
            self.write_detailed_report(f"Ошибка при обновлении статуса события {event_id}: {e}")

    def handle_event_logic(self, event):
        panel_id = event.get('panel_id')
        event_id = event.get('event_id')
        event_code = event.get('code')
        address = event.get('address')
        event_time = event.get('time_event')
        company_name = event.get('company_name')
        self.logger.debug(f"Обработка логики события {event_id}.")
        self.write_detailed_report(f"Начало обработки логики события {event_id}.")
        try:
            if not self.create_archive_event(event):
                self.logger.error(f"Не удалось создать запись в архиве для события {event_id}")
                self.write_detailed_report(f"Не удалось создать запись в архиве для события {event_id}")
                self.update_event_status(panel_id, event_id, state_event=0)
                return
            self.create_archive_record(event_id, 'Прием на обработку')

            template_vars = {
                'object_id': panel_id,
                'object_id_digits': number_to_spelled_digits(panel_id),
                'event_time': event_time.strftime('%Y-%m-%d %H:%M:%S'),
                'address': address,
                'event_code': event_code,
                'company_name': company_name
            }
            audio_files = self.synthesizer.synthesize(panel_id, template_vars, self.tts_template)
            if not audio_files or not audio_files.get('mp3'):
                self.logger.error(f"Не удалось сгенерировать аудио для события {event_id}")
                self.write_detailed_report(f"Не удалось сгенерировать аудио для события {event_id}")
                self.update_event_status(panel_id, event_id, state_event=0)
                return
            file_path = audio_files['mp3']
            file_name = os.path.splitext(os.path.basename(file_path))[0]
            self.logger.debug(f"Аудиофайл для события {event_id}: {file_path}")
            self.write_detailed_report(f"Аудиофайл для события {event_id}: {file_path}")

            responsibles = self.get_responsibles(panel_id)
            if not responsibles:
                self.logger.warning(f"Нет ответственных лиц для объекта {panel_id}. Завершаем.")
                self.write_detailed_report(f"Нет ответственных лиц для объекта {panel_id}. Завершаем.")
                self.finalize_event(panel_id, event_id)
                return
            self.event_responsibles[event_id] = responsibles
            self.event_call_attempts[event_id] = 0
            self.call_responsibles(event_id, file_name, panel_id, event)
        except Exception as e:
            self.logger.error(f"Ошибка при обработке события {event_id}: {e}")
            self.write_detailed_report(f"Ошибка при обработке события {event_id}: {e}")
            self.update_event_status(panel_id, event_id, state_event=0)

    def get_responsibles(self, panel_id):
        query = """
        SELECT r.ResponsiblesList_id, COALESCE(rt.PhoneNo, '') as PhoneNo,
               rl.Responsible_Name
        FROM dbo.Responsibles r
        LEFT JOIN dbo.ResponsibleTel rt ON rt.ResponsiblesList_id = r.ResponsiblesList_id
        LEFT JOIN dbo.ResponsiblesList rl ON rl.ResponsiblesList_id = r.ResponsiblesList_id
        WHERE r.Panel_id = %s
        ORDER BY r.Responsible_id ASC
        """
        try:
            rows = self.db_connector.fetchall(query, (panel_id,))
            responsibles = []
            for row in rows:
                resp_id, phone, name = row['ResponsiblesList_id'], row['PhoneNo'], row['Responsible_Name']
                responsibles.append({
                    'responsibles_list_id': resp_id,
                    'phone_number': phone,
                    'responsible_name': name
                })
            self.logger.debug(f"Найдено {len(responsibles)} ответственных для Panel_id={panel_id}.")
            self.write_detailed_report(f"Найдено {len(responsibles)} ответственных для Panel_id={panel_id}.")
            return responsibles
        except Exception as e:
            self.logger.error(f"Ошибка при получении ответственных для Panel_id={panel_id}: {e}")
            self.write_detailed_report(f"Ошибка при получении ответственных для Panel_id={panel_id}: {e}")
            return []

    def call_responsibles(self, event_id, file_name, panel_id, event):
        responsibles = self.event_responsibles.get(event_id, [])
        attempt = self.event_call_attempts.get(event_id, 0)
        if attempt >= len(responsibles):
            self.logger.info(f"Все ответственные обзвонены (event_id={event_id}). Отправка SMS первому.")
            self.write_detailed_report(f"Все ответственные обзвонены для события {event_id}. Отправка SMS первому.")
            if responsibles:
                self.send_sms_to_responsible(responsibles[0], event_id, panel_id, event)
            self.finalize_event(panel_id, event_id)
            return

        responsible = responsibles[attempt]
        phone_number = responsible.get('phone_number')
        responsible_name = responsible.get('responsible_name')
        if not phone_number:
            self.logger.warning(f"У {responsible_name} (event_id={event_id}) нет номера телефона. Следующий.")
            self.write_detailed_report(f"У {responsible_name} (event_id={event_id}) нет номера телефона. Следующий.")
            self.event_call_attempts[event_id] += 1
            self.call_responsibles(event_id, file_name, panel_id, event)
            return

        phone_to_call = self.test_phone_number if self.test_mode else phone_number
        self.logger.debug(f"Инициируем звонок на номер {phone_to_call} для события {event_id}.")
        self.write_detailed_report(f"Инициируем звонок на номер {phone_to_call} для события {event_id}.")
        action_id = self.call_manager.make_call(phone_to_call, file_name, panel_id)
        if not action_id:
            self.logger.error(f"Не удалось инициировать звонок для события {event_id} на {phone_to_call}. Следующий.")
            self.write_detailed_report(f"Не удалось инициировать звонок для события {event_id} на {phone_to_call}.")
            time.sleep(self.call_delay_seconds)
            self.event_call_attempts[event_id] += 1
            self.call_responsibles(event_id, file_name, panel_id, event)
            return

        # Добавляем запись с блокировкой
        with self.action_id_lock:
            self.action_id_to_call_info[action_id] = {
                'panel_id': panel_id,
                'event_id': event_id,
                'code': event.get('code'),
                'time_event': event.get('time_event'),
                'address': event.get('address'),
                'company_name': event.get('company_name'),
                'phone_number': phone_number,
                'responsible_name': responsible_name,
                'file_name': file_name,
                'event': event
            }
        report_data = {
            'Дата и время обработки': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'ID объекта': panel_id,
            'ID события': event_id,
            'Код события': event.get('code'),
            'Время события': event.get('time_event').strftime('%Y-%m-%d %H:%M:%S'),
            'Адрес': event.get('address'),
            'Название компании': event.get('company_name'),
            'Ответственный': responsible_name,
            'Номер телефона': phone_number,
            'Статус': 'Звонок инициирован',
            'Дополнительная информация': f"ActionID: {action_id}"
        }
        self.write_to_report(report_data)
        self.logger.info(f"Звонок инициирован на номер {phone_to_call} для события {event_id}, ActionID={action_id}.")
        self.write_detailed_report(f"Звонок инициирован на номер {phone_to_call} для события {event_id}, ActionID={action_id}.")

    def handle_call_event(self, uniqueid, status, call_info, extra_info=None):
        expected_statuses = ['ANSWERED', 'NO ANSWER', 'BUSY', 'FAILED', 'CANCELED', 'HUNG_UP', 'BRIDGED']
        panel_id = call_info.get('panel_id')
        phone_number = call_info.get('phone_number')
        event_id = call_info.get('event_id')
        code = call_info.get('code')
        event_time = call_info.get('time_event')
        address = call_info.get('address')
        company_name = call_info.get('company_name')
        responsible_name = call_info.get('responsible_name')

        self.logger.info(f"[CALL EVENT] ActionID={uniqueid}, Status={status}, Phone={phone_number}, EventID={event_id}")
        self.write_detailed_report(f"[CALL EVENT] ActionID={uniqueid}, Status={status}, Phone={phone_number}, EventID={event_id}")

        if status not in expected_statuses:
            return

        if status in ['ANSWERED', 'BRIDGED']:
            rep_status = 'Звонок принят' if status == 'ANSWERED' else 'Звонок соединён'
            report_data = {
                'Дата и время обработки': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                'ID объекта': panel_id,
                'ID события': event_id,
                'Код события': code,
                'Время события': event_time.strftime('%Y-%m-%d %H:%M:%S'),
                'Адрес': address,
                'Название компании': company_name,
                'Ответственный': responsible_name,
                'Номер телефона': phone_number,
                'Статус': rep_status,
                'Дополнительная информация': status
            }
            self.write_to_report(report_data)
            self.finalize_event(panel_id, event_id)

        elif status in ['NO ANSWER', 'BUSY', 'FAILED', 'CANCELED', 'HUNG_UP']:
            self.logger.warning(f"Звонок неуспешен ({status}) для номера {phone_number}, event_id={event_id}.")
            self.write_detailed_report(f"Звонок неуспешен ({status}) для номера {phone_number}, event_id={event_id}.")
            time.sleep(self.call_delay_seconds)
            self.event_call_attempts[event_id] += 1
            self.call_responsibles(event_id, call_info.get('file_name'), panel_id, call_info.get('event'))

        with self.action_id_lock:
            if uniqueid in self.action_id_to_call_info:
                del self.action_id_to_call_info[uniqueid]
                self.write_detailed_report(f"ActionID {uniqueid} удалён из отслеживания.")

    def finalize_event(self, panel_id, event_id):
        self.logger.debug(f"Финализация события {event_id} для объекта {panel_id}.")
        self.write_detailed_report(f"Финализация события {event_id} для объекта {panel_id}.")
        self.update_event_status(panel_id, event_id, state_event=2)
        self.delete_dependent_records(event_id)
        self.delete_event_from_temp(panel_id, event_id)
        self.create_archive_record(event_id, 'Окончание обработки')
        self.logger.info(f"Обработка события {event_id} для объекта {panel_id} завершена.")
        self.write_detailed_report(f"Обработка события {event_id} для объекта {panel_id} завершена.")
        if self.parent:
            self.parent.remove_alarm_card(panel_id)

    def delete_dependent_records(self, event_id):
        delete_sql = "DELETE FROM dbo.TempDetails WHERE Event_id = %s"
        try:
            self.db_connector.execute(delete_sql, (event_id,))
            self.db_connector.commit()
            self.logger.debug(f"TempDetails для event_id={event_id} удалены.")
            self.write_detailed_report(f"TempDetails для event_id={event_id} удалены.")
        except Exception as e:
            self.logger.error(f"Ошибка при удалении TempDetails (event_id={event_id}): {e}")
            self.write_detailed_report(f"Ошибка при удалении TempDetails (event_id={event_id}): {e}")

    def delete_event_from_temp(self, panel_id, event_id):
        delete_sql = "DELETE FROM dbo.Temp WHERE Panel_id = %s AND Event_id = %s"
        try:
            self.db_connector.execute(delete_sql, (panel_id, event_id))
            self.db_connector.commit()
            self.logger.debug(f"Событие {event_id} удалено из Temp.")
            self.write_detailed_report(f"Событие {event_id} удалено из Temp.")
        except Exception as e:
            self.logger.error(f"Ошибка при удалении события {event_id} из Temp: {e}")
            self.write_detailed_report(f"Ошибка при удалении события {event_id} из Temp: {e}")

    def send_sms_to_responsible(self, responsible, event_id, panel_id, event):
        phone_number = responsible.get('phone_number')
        responsible_name = responsible.get('responsible_name')
        if not phone_number:
            self.logger.warning(f"У {responsible_name} нет номера для SMS.")
            self.write_detailed_report(f"У {responsible_name} нет номера для SMS.")
            return
        phone_to_sms = self.test_phone_number if self.test_mode else phone_number
        try:
            message = self.sms_template.format(
                object_id=panel_id,
                event_code=event.get('code'),
                event_time=event.get('time_event').strftime('%Y-%m-%d %H:%M:%S'),
                company_name=event.get('company_name'),
                address=event.get('address')
            )
            self.logger.debug(f"Сформировано сообщение SMS для события {event_id}: {message}")
            self.write_detailed_report(f"Сформировано сообщение SMS для события {event_id}.")
        except Exception as e:
            self.logger.error(f"Ошибка при форматировании SMS: {e}")
            self.write_detailed_report(f"Ошибка при форматировании SMS для события {event_id}: {e}")
            return

        sms_sent = send_http_sms(
            phone_number=phone_to_sms,
            message=message,
            url=self.sms_url,
            login=self.sms_login,
            password=self.sms_password,
            shortcode=self.sms_shortcode
        )
        if sms_sent:
            self.logger.info(f"SMS отправлено на номер {phone_to_sms}.")
            self.write_detailed_report(f"SMS отправлено на номер {phone_to_sms} для события {event_id}.")
            report_data = {
                'Дата и время обработки': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                'ID объекта': panel_id,
                'ID события': event_id,
                'Код события': event.get('code'),
                'Время события': event.get('time_event').strftime('%Y-%m-%d %H:%M:%S'),
                'Адрес': event.get('address'),
                'Название компании': event.get('company_name'),
                'Ответственный': responsible_name,
                'Номер телефона': phone_number,
                'Статус': 'SMS отправлено',
                'Дополнительная информация': ''
            }
            self.write_to_report(report_data)
        else:
            self.logger.error(f"Не удалось отправить SMS на {phone_to_sms}.")
            self.write_detailed_report(f"Не удалось отправить SMS на {phone_to_sms} для события {event_id}.")

    def create_archive_event(self, event):
        if not self.db_connector:
            self.logger.error("db_connector не инициализирован.")
            self.write_detailed_report("db_connector не инициализирован.")
            return False
        date_now = datetime.now()
        table_name = f"pult4db_archives.dbo.archive{date_now.strftime('%Y%m')}01"
        check_sql = f"SELECT COUNT(*) as cnt FROM {table_name} WHERE Event_id = %s"
        insert_sql = f"""
        INSERT INTO {table_name} (
            Event_id, Date_Key, Panel_id, Group_, Line, Zone, Code, CodeGroup,
            TimeEvent, Phone, MeterCount, TimeMeterCount, StateEvent,
            Event_Parent_id, Result_Text, BitMask, DeviceEventTime, ResultID
        )
        VALUES (%s, %s, %s, NULL, NULL, NULL, %s, NULL, %s, NULL, NULL, NULL, NULL, NULL, NULL, 0, NULL, NULL)
        """
        params = (event['event_id'], int(date_now.strftime('%Y%m%d')), event['panel_id'],
                  event['code'], event['time_event'])
        try:
            result = self.db_connector.fetch_one(check_sql, (event['event_id'],))
            cnt = result.get('cnt', 0) if isinstance(result, dict) else (result[0] if result else 0)

            if cnt > 0:
                self.logger.info(f"Событие {event['event_id']} уже в архиве.")
                self.write_detailed_report(f"Событие {event['event_id']} уже в архиве.")
                return True

            self.db_connector.execute(insert_sql, params)
            self.db_connector.commit()
            self.logger.info(f"Запись в архив {table_name} создана.")
            self.write_detailed_report(f"Запись в архив {table_name} создана для события {event['event_id']}.")
            return True
        except Exception as e:
            self.db_connector.rollback()
            self.logger.error(f"Ошибка при создании записи в архив: {e}")
            self.write_detailed_report(f"Ошибка при создании записи в архив для события {event['event_id']}: {e}")
            return False

    def create_archive_record(self, event_id, name_state):
        if not self.db_connector:
            self.logger.error("db_connector не инициализирован.")
            self.write_detailed_report("db_connector не инициализирован для создания записи в архиве.")
            return
        date_now = datetime.now()
        table_name = f"pult4db_archives.dbo.eventservice{date_now.strftime('%Y%m')}01"
        sql = f"""
        INSERT INTO {table_name} (
            NameState, Event_id, Computer, OperationTime, Date_Key, PersonName
        )
        VALUES (%s, %s, %s, %s, %s, %s)
        """
        params = (
            name_state,
            event_id,
            socket.gethostname(),
            datetime.now(),
            int(date_now.strftime('%Y%m%d')),
            'Смена 1.0'
        )
        try:
            self.db_connector.execute(sql, params)
            self.db_connector.commit()
            self.logger.debug(f"Запись в {table_name} создана для события {event_id}.")
            self.write_detailed_report(f"Запись в архиве {table_name} создана для события {event_id}.")
        except Exception as e:
            self.db_connector.rollback()
            self.logger.error(f"Ошибка при создании записи в {table_name}: {e}")
            self.write_detailed_report(f"Ошибка при создании записи в {table_name} для события {event_id}: {e}")

    def stop(self):
        self.stop_processing()
        if self.call_manager:
            self.call_manager.stop()
            self.write_detailed_report("CallManager остановлен.")
        if self.synthesizer:
            self.synthesizer.stop_http_server()
            self.write_detailed_report("VoiceSynthesizer остановлен.")
        if self.db_connector:
            self.db_connector.disconnect()
            self.write_detailed_report("DBConnector отключён.")
        self.logger.info("EventProcessor остановлен.")
        self.write_detailed_report("EventProcessor полностью остановлен.")
