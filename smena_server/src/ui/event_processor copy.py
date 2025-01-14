import threading
import time
from datetime import datetime, timedelta
from PyQt5.QtCore import QObject, pyqtSignal
import os
import logging
import socket
import queue
import csv
import pymysql

from ui.voice_synthesizer import VoiceSynthesizer
from ui.call_manager import CallManager
from ui.sms_manager import send_http_sms
from ui.utils import number_to_spelled_digits
from db_connector import DBConnector


class CDRConnector:
    """Подключение к базе данных CDR (MySQL)."""
    def __init__(self, host, port, user, password, database, table):
        self.table = table
        try:
            self.connection = pymysql.connect(
                host=host,
                port=port,
                user=user,
                password=password,
                database=database,
                charset='utf8mb4',
                cursorclass=pymysql.cursors.DictCursor,
                autocommit=True
            )
            self.cursor = self.connection.cursor()
            logging.info("Успешно подключились к базе данных CDR.")
        except Exception as e:
            logging.error(f"Ошибка при подключении к базе данных CDR: {e}")
            self.connection = None

    def fetch_one(self, query, params=None):
        if not self.connection:
            return None
        try:
            self.cursor.execute(query, params)
            return self.cursor.fetchone()
        except Exception as e:
            logging.error(f"Ошибка при запросе к CDR: {e}")
            return None

    def disconnect(self):
        if self.connection:
            self.connection.close()
            self.connection = None
            logging.info("Отключились от базы данных CDR.")


class EventProcessor(QObject):
    processing_started = pyqtSignal()
    processing_stopped = pyqtSignal()
    alarm_processed = pyqtSignal(str)

    def __init__(self, config, db_connector, parent=None):
        super().__init__(parent)
        self.config = config
        self.parent = parent
        self.db_connector = db_connector

        # Настройка логирования
        self.logger = logging.getLogger('event_processor')
        self.logger.setLevel(logging.DEBUG)
        handler = logging.StreamHandler()
        formatter = logging.Formatter(
            '%(asctime)s - event_processor - %(levelname)s - %(message)s')
        handler.setFormatter(formatter)
        if not self.logger.handlers:
            self.logger.addHandler(handler)

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
        # Инициация звонков и отслеживание статусов через CallManager
        self.call_manager = CallManager(config=self.config, callback=self.handle_call_event)

        # Настройки SMS
        self.sms_url = self.config['SMS']['url']
        self.sms_login = self.config['SMS']['login']
        self.sms_password = self.config['SMS']['password']
        self.sms_shortcode = self.config['SMS']['shortcode']

        # Подключение к CDR (MySQL, если нужно)
        self.cdr_connector = CDRConnector(
            host=self.config.get('CDRDatabase', 'host'),
            port=int(self.config.get('CDRDatabase', 'port', fallback='3306')),
            user=self.config.get('CDRDatabase', 'user'),
            password=self.config.get('CDRDatabase', 'password'),
            database=self.config.get('CDRDatabase', 'database'),
            table=self.config.get('CDRDatabase', 'table')
        )

        # Очередь и потоки
        self.event_queue = queue.Queue()
        self.max_concurrent_events = int(self.config.get('EventProcessing', 'max_concurrent_events', fallback='5'))
        self.event_semaphore = threading.Semaphore(self.max_concurrent_events)
        self.processing_threads = []
        self.processing_enabled = False

        # Отслеживание времени последней обработки объектов
        # panel_id -> datetime (когда в последний раз обрабатывали)
        self.active_events = {}
        self.lock = threading.Lock()

        # Сопоставление звонков
        self.uniqueid_event_map = {}   # uniqueid -> событие
        self.actionid_event_map = {}   # action_id -> событие
        self.uniqueid_event_lock = threading.Lock()

        self.call_statuses = {}
        self.call_status_lock = threading.Lock()

        # Для хранения списка ответственных и текущего индекса попытки
        # event_id -> [ { ...responsible1... }, { ...responsible2... }, ... ]
        self.event_responsibles = {}
        # event_id -> int (какой индекс ответственного обрабатываем)
        self.event_call_attempts = {}

        # Время ожидания между дозвонами разным ответственным (секунды)
        self.call_delay_seconds = int(self.config.get(
            'EventProcessing',
            'call_delay_seconds',
            fallback='180'
        ))

        # Инициализация файлов отчётов
        script_dir = os.path.dirname(os.path.abspath(__file__))
        self.report_dir = os.path.join(script_dir, 'otcet')
        os.makedirs(self.report_dir, exist_ok=True)

        self.report_lock = threading.Lock()
        self.report_file_path = os.path.join(self.report_dir, datetime.now().strftime('%Y.%m.01') + '.csv')
        self.initialize_report_file()

    def load_config_parameters(self):
        # Интервал проверки базы (сколько ждать до следующей выборки)
        self.repeat_interval = timedelta(
            seconds=int(self.config.get('EventProcessing', 'repeat_interval', fallback='30'))
        )
        self.event_codes = self.load_event_codes_from_config()
        self.test_mode = self.config.getboolean('Testing', 'test_mode', fallback=False)
        self.test_phone_number = self.config.get('Testing', 'test_phone_number', fallback='')
        self.sms_template = self.config.get('Message', 'sms_text', fallback='')
        self.tts_template = self.config.get('Message', 'tts_text', fallback='')
        self.use_ssml = self.config.getboolean('Message', 'use_ssml', fallback=False)
        self.call_timeout = int(self.config.get('EventProcessing', 'call_timeout', fallback='60'))
        self.max_call_attempts = int(self.config.get('EventProcessing', 'max_call_attempts', fallback='3'))

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
        """Потокобезопасная запись в CSV-отчёт."""
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

    def start_processing(self):
        if not self.processing_enabled:
            self.processing_enabled = True
            self.logger.info("Обработка событий запущена.")
            self.processing_started.emit()
            # Запускаем основной поток, который периодически
            # загружает новые события и ставит их в очередь
            self.processing_thread = threading.Thread(
                target=self.event_processing_loop,
                daemon=True
            )
            self.processing_thread.start()
        else:
            self.logger.info("Обработка событий уже запущена.")

    def stop_processing(self):
        if self.processing_enabled:
            self.processing_enabled = False
            self.logger.info("Обработка событий остановлена.")
            self.processing_stopped.emit()

            # Посылаем None, чтобы разбудить все воркеры
            for _ in self.processing_threads:
                self.event_queue.put(None)
            for t in self.processing_threads:
                t.join()

            self.processing_threads.clear()

            # Очищаем очередь
            with self.event_queue.mutex:
                self.event_queue.queue.clear()

            self.logger.debug("Все рабочие потоки остановлены.")
        else:
            self.logger.info("Обработка событий уже остановлена.")

    def is_processing_active(self):
        return self.processing_enabled

    def enqueue_event(self, event):
        """Помещаем событие в очередь на обработку."""
        self.event_queue.put(event)
        self.logger.debug(f"Событие {event['event_id']} добавлено в очередь.")

    def event_processing_loop(self):
        """Основной цикл, который периодически подгружает события из БД и стартует рабочие потоки."""
        self.logger.debug("Начало цикла обработки событий.")
        while self.processing_enabled:
            self.logger.debug("Загрузка событий из базы данных.")
            events = self.load_events_from_database()

            for event in events:
                self.enqueue_event(event)

            # Если потоки не запущены — запускаем
            if not self.processing_threads:
                self.logger.debug("Запуск рабочих потоков.")
                for _ in range(self.max_concurrent_events):
                    t = threading.Thread(target=self.event_worker, daemon=True)
                    t.start()
                    self.processing_threads.append(t)

            # Ждём repeat_interval до следующего запроса
            self.logger.debug(f"Цикл завершен. Ждем {self.repeat_interval.total_seconds()} сек.")
            time.sleep(self.repeat_interval.total_seconds())

        self.logger.debug("Цикл обработки событий завершен.")

    def event_worker(self):
        """Поток для последовательной обработки событий из очереди."""
        self.logger.debug("Рабочий поток запущен.")
        while True:
            event = self.event_queue.get()
            if event is None:
                self.logger.debug("Сигнал завершения рабочего потока (None).")
                break
            if not self.processing_enabled:
                self.logger.info("Обработка событий отключена.")
                self.event_queue.task_done()
                continue

            with self.event_semaphore:
                self.process_event(event)

            self.event_queue.task_done()

        self.logger.debug("Рабочий поток завершен.")

    def load_events_from_database(self):
        """Загружаем из таблицы Temp все события, StateEvent=0, с нужными кодами."""
        if not self.event_codes:
            self.logger.warning("Список кодов событий пуст.")
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
                    'panel_id': row[0],
                    'event_id': row[1],
                    'code': row[2],
                    'time_event': row[3],
                    'address': row[4],
                    'company_name': row[5],
                    'state_event': row[6]
                })
            self.logger.debug(f"Загружено {len(events)} событий.")
            return events
        except Exception as e:
            self.logger.error(f"Ошибка при загрузке событий: {e}")
            return []

    def process_event(self, event):
        """Обрабатывает одно событие: проверяет, можно ли обрабатывать, ставит статус, вызывает логику звонков."""
        if not self.processing_enabled:
            self.logger.info("Обработка событий отключена.")
            return

        panel_id = event.get('panel_id')
        event_id = event.get('event_id')

        # Проверяем, можно ли обрабатывать объект (условия "следующие сутки" и "прошло > 4 часа").
        if not self.can_process_event(panel_id):
            self.logger.info(f"Событие для объекта {panel_id} пропущено (не наступил нужный период).")
            return

        # Ставим StateEvent=1 (в обработке)
        self.update_event_status(panel_id, event_id, state_event=1)

        with self.lock:
            # Запоминаем время последней обработки объекта
            self.active_events[panel_id] = datetime.now()

        self.handle_event_logic(event)

        # Сбросим "активную обработку" (если нужно)
        with self.lock:
            if panel_id in self.active_events:
                # Но в данном случае мы не стираем совсем, 
                # так как время остаётся для проверки в будущем
                pass

    def can_process_event(self, panel_id):
        """
        Разрешаем обработку объекта, если:
         1) Сейчас дата больше, чем дата последней обработки.
         2) (now - last_time) >= 4 часов.
        Если записи нет — обрабатываем сразу.
        """
        now = datetime.now()

        with self.lock:
            last_time = self.active_events.get(panel_id, None)

        if last_time is None:
            # Ещё не обрабатывали — можно
            return True

        # Если текущая дата = дата последней обработки — нельзя (в одной дате обрабатываем 1 раз).
        if now.date() == last_time.date():
            self.logger.debug(
                f"Object {panel_id} уже обрабатывался сегодня. Пропускаем."
            )
            return False

        # Иначе проверяем, что прошли сутки + 4 часа с момента last_time.
        # Т.к. now.date() > last_time.date() (следующий день), нужно ещё проверить 4 часа:
        hours_diff = (now - last_time).total_seconds() / 3600.0
        if hours_diff < 4.0:
            self.logger.debug(
                f"Object {panel_id} обрабатывался {hours_diff:.1f} ч назад (меньше 4). Пропускаем."
            )
            return False

        # Если и дата стала больше, и >= 4 часов, то можно
        return True

    def update_event_status(self, panel_id, event_id, state_event):
        """Обновляет поле StateEvent в таблице Temp для конкретного события."""
        update_sql = """
        UPDATE dbo.Temp SET StateEvent = %s 
        WHERE Panel_id = %s AND Event_id = %s
        """
        try:
            rows_affected = self.db_connector.execute(
                update_sql, (state_event, panel_id, event_id)
            )
            self.db_connector.commit()
            if rows_affected > 0:
                self.logger.debug(f"Статус события {event_id} -> {state_event}.")
            else:
                self.logger.warning(
                    f"Статус события {event_id} не обновлен (нет затронутых строк)."
                )
        except Exception as e:
            self.logger.error(f"Ошибка при обновлении статуса: {e}")

    def handle_event_logic(self, event):
        """Основная логика: создание архива, TTS-файла, поиск ответственных, обзвон."""
        panel_id = event.get('panel_id')
        event_id = event.get('event_id')
        event_code = event.get('code')
        address = event.get('address')
        event_time = event.get('time_event')
        company_name = event.get('company_name')

        try:
            # Создаём запись в архивной таблице (archiveYYYYmm01)
            if not self.create_archive_event(event):
                self.logger.error(f"Не удалось создать запись в архиве для события {event_id}")
                self.update_event_status(panel_id, event_id, 0)
                return

            # Создаём запись в eventserviceYYYYmm01
            self.create_archive_record(event_id, 'Прием на обработку')

            template_vars = {
                'object_id': panel_id,
                'object_id_digits': number_to_spelled_digits(panel_id),
                'event_time': event_time.strftime('%Y-%m-%d %H:%M:%S'),
                'address': address,
                'event_code': event_code,
                'company_name': company_name
            }

            audio_files = self.synthesizer.synthesize(
                panel_id,
                template_vars,
                self.tts_template
            )
            if not audio_files or not audio_files.get('mp3'):
                self.logger.error(f"Не удалось сгенерировать аудио для события {event_id}")
                self.update_event_status(panel_id, event_id, 0)
                return

            file_path = audio_files['mp3']
            file_name = os.path.splitext(os.path.basename(file_path))[0]

            # Ищем ответственных
            responsibles = self.get_responsibles(panel_id)
            if not responsibles:
                self.logger.warning(
                    f"Нет ответственных лиц для объекта {panel_id}. Завершаем."
                )
                self.finalize_event(panel_id, event_id)
                return

            # Запоминаем список и начинаем с 0-го
            self.event_responsibles[event_id] = responsibles
            self.event_call_attempts[event_id] = 0

            # Запускаем обзвон
            self.call_responsibles(event_id, file_name, panel_id, event)

        except Exception as e:
            self.logger.error(f"Ошибка при обработке события {event_id}: {e}")
            self.update_event_status(panel_id, event_id, 0)

    def get_responsibles(self, panel_id):
        """Возвращает список ответственных (id, телефон, имя) для данного panel_id."""
        query = """
        SELECT r.ResponsiblesList_id, COALESCE(rt.PhoneNo, '') as PhoneNo, 
               rl.Responsible_Name
        FROM dbo.Responsibles r
        LEFT JOIN dbo.ResponsibleTel rt 
            ON rt.ResponsiblesList_id = r.ResponsiblesList_id
        LEFT JOIN dbo.ResponsiblesList rl 
            ON rl.ResponsiblesList_id = r.ResponsiblesList_id
        WHERE r.Panel_id = %s
        ORDER BY r.Responsible_id ASC
        """
        try:
            rows = self.db_connector.fetchall(query, (panel_id,))
            responsibles = []
            for row in rows:
                resp_id, phone, name = row[0], row[1], row[2]
                responsibles.append({
                    'responsibles_list_id': resp_id,
                    'phone_number': phone,
                    'responsible_name': name
                })
            return responsibles
        except Exception as e:
            self.logger.error(
                f"Ошибка при получении ответственных для Panel_id={panel_id}: {e}"
            )
            return []

    def call_responsibles(self, event_id, file_name, panel_id, event):
        """Инициирует звонок текущему ответственному (event_call_attempts), 
           если все исчерпаны — отправляем SMS первому и завершаем."""
        responsibles = self.event_responsibles.get(event_id, [])
        attempt = self.event_call_attempts.get(event_id, 0)

        # Если всех обзвонили — отправка SMS первому и финализация
        if attempt >= len(responsibles):
            self.logger.info(f"Все ответственные обзвонены (event_id={event_id}). Отправка SMS первому.")
            if responsibles:
                self.send_sms_to_responsible(responsibles[0], event_id, panel_id, event)
            self.finalize_event(panel_id, event_id)
            return

        # Берём ответственного по индексу
        responsible = responsibles[attempt]
        phone_number = responsible.get('phone_number')
        responsible_name = responsible.get('responsible_name')

        if not phone_number:
            self.logger.warning(
                f"У {responsible_name} (event_id={event_id}) нет номера. Следующий."
            )
            self.event_call_attempts[event_id] += 1
            self.call_responsibles(event_id, file_name, panel_id, event)
            return

        # Если test_mode=True, звоним на тестовый номер
        phone_to_call = self.test_phone_number if self.test_mode else phone_number
        action_id = self.call_manager.make_call(phone_to_call, file_name, panel_id)

        if not action_id:
            self.logger.error(
                f"Не удалось инициировать звонок для события {event_id} на {phone_to_call}. Следующий."
            )
            # Делаем паузу перед тем, как позвонить следующему
            time.sleep(self.call_delay_seconds)
            self.event_call_attempts[event_id] += 1
            self.call_responsibles(event_id, file_name, panel_id, event)
            return

        # Запоминаем, к какому событию относится этот action_id
        self.actionid_event_map[action_id] = {
            'event_id': event_id,
            'panel_id': panel_id,
            'responsible': responsible,
            'file_name': file_name,
            'event': event
        }

        # Пишем в отчёт
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
            'Дополнительная информация': ''
        }
        self.write_to_report(report_data)

    def handle_call_event(self, action_id, event_type, call_info, extra_info=None):
        """
        Коллбэк из CallManager при событиях AMI:
         - 'ORIGINATE_RESPONSE': Asterisk ответил на Originate
         - 'HANGUP': звонок завершён
        """
        if event_type == 'ORIGINATE_RESPONSE':
            uniqueid = extra_info.get('uniqueid')
            response = extra_info.get('response')

            if response == 'Success' and uniqueid:
                mapping = self.actionid_event_map.pop(action_id, None)
                if mapping:
                    with self.uniqueid_event_lock:
                        self.uniqueid_event_map[uniqueid] = mapping
                else:
                    self.logger.warning(
                        f"ORIGINATE_RESPONSE: событие не найдено для action_id={action_id}."
                    )
            else:
                # Не удалось инициировать звонок — звоним следующему
                mapping = self.actionid_event_map.pop(action_id, None)
                if mapping:
                    event_id = mapping['event_id']
                    panel_id = mapping['panel_id']
                    file_name = mapping['file_name']
                    event = mapping['event']

                    self.logger.warning(
                        f"ORIGINATE_RESPONSE != 'Success' (event_id={event_id}). Следующий ответственный..."
                    )
                    time.sleep(self.call_delay_seconds)

                    self.event_call_attempts[event_id] += 1
                    self.call_responsibles(event_id, file_name, panel_id, event)

        elif event_type == 'HANGUP':
            uniqueid = extra_info.get('uniqueid')
            disposition = extra_info.get('disposition')

            if not uniqueid:
                self.logger.error("HANGUP без uniqueid — пропускаем.")
                return

            with self.uniqueid_event_lock:
                mapping = self.uniqueid_event_map.pop(uniqueid, None)

            if not mapping:
                self.logger.warning(
                    f"HANGUP для uniqueid={uniqueid}, но событие не найдено."
                )
                return

            event_id = mapping['event_id']
            panel_id = mapping['panel_id']
            responsible = mapping['responsible']
            event = mapping['event']
            responsible_name = responsible['responsible_name']
            phone_number = responsible['phone_number']
            file_name = mapping['file_name']

            if disposition == 'ANSWERED':
                # Если кто-то ответил — всё, завершаем обработку
                self.logger.info(
                    f"Звонок {uniqueid} (event_id={event_id}) успешно завершен (ANSWERED)."
                )
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
                    'Статус': 'Звонок успешно завершен',
                    'Дополнительная информация': disposition
                }
                self.write_to_report(report_data)

                self.finalize_event(panel_id, event_id)
            else:
                # Если не ANSWERED, переходим к следующему
                self.logger.warning(
                    f"Звонок {uniqueid} (event_id={event_id}) завершен: {disposition}. Следующий."
                )
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
                    'Статус': f"Звонок завершен: {disposition}",
                    'Дополнительная информация': ''
                }
                self.write_to_report(report_data)

                time.sleep(self.call_delay_seconds)

                self.event_call_attempts[event_id] += 1
                self.call_responsibles(event_id, file_name, panel_id, event)

    def finalize_event(self, panel_id, event_id):
        """
        Вызывается при успешном завершении обработки события:
         - Поставить StateEvent=2
         - Удалить зависимые записи TempDetails
         - Удалить событие из Temp
         - Записать в архив
         - Уведомить GUI (remove_alarm_card)
        """
        self.update_event_status(panel_id, event_id, state_event=2)
        self.delete_dependent_records(event_id)
        self.delete_event_from_temp(panel_id, event_id)

        self.create_archive_record(event_id, 'Окончание обработки')
        self.logger.info(
            f"Обработка события {event_id} для объекта {panel_id} завершена."
        )

        if self.parent:
            self.parent.remove_alarm_card(panel_id)

    def delete_dependent_records(self, event_id):
        """Удаляем записи из TempDetails, связанные только с данным event_id."""
        delete_sql = """
        DELETE FROM dbo.TempDetails WHERE Event_id = %s
        """
        try:
            self.db_connector.execute(delete_sql, (event_id,))
            self.db_connector.commit()
        except Exception as e:
            self.logger.error(f"Ошибка при удалении TempDetails (event_id={event_id}): {e}")

    def delete_event_from_temp(self, panel_id, event_id):
        """Удаляем конкретное событие из Temp."""
        delete_sql = "DELETE FROM dbo.Temp WHERE Panel_id = %s AND Event_id = %s"
        try:
            self.db_connector.execute(delete_sql, (panel_id, event_id))
            self.db_connector.commit()
        except Exception as e:
            self.logger.error(f"Ошибка при удалении события {event_id} из Temp: {e}")

    def send_sms_to_responsible(self, responsible, event_id, panel_id, event):
        """Отправка SMS ответственному (используется только для 1-го из списка, 
           когда никому не дозвонились)."""
        phone_number = responsible.get('phone_number')
        responsible_name = responsible.get('responsible_name')

        if not phone_number:
            self.logger.warning(f"У {responsible_name} нет номера для SMS.")
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
        except Exception as e:
            self.logger.error(f"Ошибка при форматировании SMS: {e}")
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

    def create_archive_event(self, event):
        """Создаём запись в архивной таблице archiveYYYYmm01, если ещё нет."""
        if not self.db_connector:
            self.logger.error("db_connector не инициализирован.")
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
        params = (
            event['event_id'],
            int(date_now.strftime('%Y%m%d')),
            event['panel_id'],
            event['code'],
            event['time_event']
        )
        try:
            result = self.db_connector.fetch_one(check_sql, (event['event_id'],))
            cnt = 0
            if result is not None:
                # result может быть dict или tuple
                if isinstance(result, dict):
                    cnt = result.get('cnt', 0)
                else:
                    cnt = result[0]

            if cnt > 0:
                self.logger.info(f"Событие {event['event_id']} уже в архиве.")
                return True

            self.db_connector.execute(insert_sql, params)
            self.db_connector.commit()
            self.logger.info(f"Запись в архив {table_name} создана.")
            return True
        except Exception as e:
            self.logger.error(f"Ошибка при создании записи в архив: {e}")
            return False

    def create_archive_record(self, event_id, name_state):
        """Создаём запись в eventserviceYYYYmm01 об изменении состояния."""
        if not self.db_connector:
            self.logger.error("db_connector не инициализирован.")
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
        except Exception as e:
            self.logger.error(f"Ошибка при создании записи в {table_name}: {e}")

    def stop(self):
        """Остановка обработки и освобождение ресурсов."""
        self.stop_processing()
        if self.call_manager:
            self.call_manager.stop()
        if self.synthesizer:
            self.synthesizer.stop_http_server()
        if self.db_connector:
            self.db_connector.disconnect()
        if self.cdr_connector:
            self.cdr_connector.disconnect()
        self.logger.info("EventProcessor остановлен.")
