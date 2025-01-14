import logging
import threading
import time
from datetime import datetime, timedelta
from PyQt5.QtCore import QObject, pyqtSignal
import os
import queue
import csv
from concurrent.futures import ThreadPoolExecutor

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

        self.logger = logging.getLogger('event_processor')
        self.logger.setLevel(logging.DEBUG)
        handler = logging.StreamHandler()
        fmt = logging.Formatter('%(asctime)s - event_processor - %(levelname)s - %(message)s')
        handler.setFormatter(fmt)
        if not self.logger.handlers:
            self.logger.addHandler(handler)

        # Параметры
        self.load_config_parameters()

        # Синтез
        self.synthesizer = VoiceSynthesizer(
            api_key=self.config['YandexCloud']['api_key'],
            folder_id=self.config['YandexCloud']['folder_id'],
            http_host=self.config['HTTPServer']['host'],
            http_port=int(self.config['HTTPServer']['port']),
            audio_base_url=self.config['HTTPServer']['base_url']
        )

        # CallManager
        self.call_manager = CallManager(config=self.config, callback=self.handle_call_event)

        # SMS
        self.sms_url = self.config['SMS']['url']
        self.sms_login = self.config['SMS']['login']
        self.sms_password = self.config['SMS']['password']
        self.sms_shortcode = self.config['SMS']['shortcode']

        # Очередь, пул потоков
        self.event_queue = queue.Queue()
        self.max_concurrent_events = int(
            self.config.get('EventProcessing', 'max_concurrent_events', fallback='5')
        )
        self.executor = ThreadPoolExecutor(max_workers=self.max_concurrent_events)
        self.futures = set()
        self.processing_enabled = False

        # Время последней обработки
        self.active_events = {}
        self.lock = threading.Lock()

        # Статусы
        self.call_statuses = {}
        self.event_responsibles = {}
        self.event_call_attempts = {}

        self.call_delay_seconds = int(
            self.config.get('EventProcessing', 'call_delay_seconds', fallback='180')
        )

        # CSV-отчёты
        script_dir = os.path.dirname(os.path.abspath(__file__))
        self.report_dir = os.path.join(script_dir, 'otcet')
        os.makedirs(self.report_dir, exist_ok=True)

        self.report_lock = threading.Lock()
        self.report_file_path = os.path.join(
            self.report_dir, datetime.now().strftime('%Y.%m.01') + '.csv'
        )
        self.initialize_report_file()

        # Флаг, чтобы "не вызывать звонки до загрузки первой партии событий"
        self.events_loaded_once = False

    def load_config_parameters(self):
        self.repeat_interval = timedelta(
            seconds=int(self.config.get('EventProcessing', 'repeat_interval', fallback='30'))
        )
        self.event_codes = self.load_event_codes()
        self.test_mode = self.config.getboolean('Testing', 'test_mode', fallback=False)
        self.test_phone_number = self.config.get('Testing', 'test_phone_number', fallback='')
        self.sms_template = self.config.get('Message', 'sms_text', fallback='')
        self.tts_template = self.config.get('Message', 'tts_text', fallback='')
        self.use_ssml = self.config.getboolean('Message', 'use_ssml', fallback=False)
        self.call_timeout = int(self.config.get('EventProcessing', 'call_timeout', fallback='60'))
        self.max_call_attempts = int(
            self.config.get('EventProcessing', 'max_call_attempts', fallback='3')
        )

    def load_event_codes(self):
        codes_str = self.config.get('EventCodes', 'codes', fallback='')
        return [c.strip() for c in codes_str.split(',') if c.strip()]

    def initialize_report_file(self):
        with self.report_lock:
            if not os.path.exists(self.report_file_path):
                with open(self.report_file_path, 'w', newline='', encoding='utf-8') as f:
                    fieldnames = [
                        'Дата и время обработки', 'ID объекта', 'ID события', 'Код события',
                        'Время события', 'Адрес', 'Название компании', 'Ответственный',
                        'Номер телефона', 'Статус', 'Дополнительная информация'
                    ]
                    writer = csv.DictWriter(f, fieldnames=fieldnames)
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
            with open(self.report_file_path, 'a', newline='', encoding='utf-8') as f:
                fieldnames = [
                    'Дата и время обработки', 'ID объекта', 'ID события', 'Код события',
                    'Время события', 'Адрес', 'Название компании', 'Ответственный',
                    'Номер телефона', 'Статус', 'Дополнительная информация'
                ]
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                writer.writerow(data)

    def start_processing(self):
        if self.processing_enabled:
            self.logger.info("Обработка уже запущена.")
            return
        self.processing_enabled = True
        self.logger.info("Обработка событий запущена.")
        self.processing_started.emit()
        t = threading.Thread(target=self.event_processing_loop, daemon=True)
        t.start()

    def stop_processing(self):
        if not self.processing_enabled:
            self.logger.info("Обработка уже остановлена.")
            return
        self.processing_enabled = False
        self.logger.info("Обработка событий остановлена.")
        self.processing_stopped.emit()

        self.executor.shutdown(wait=True)
        self.futures.clear()
        with self.event_queue.mutex:
            self.event_queue.queue.clear()
        self.logger.debug("Все рабочие потоки остановлены.")

    def is_processing_active(self):
        return self.processing_enabled

    def enqueue_event(self, evt):
        
        event_id = evt.get('event_id', 'N/A')

        
        self.logger.debug(f"Событие {event_id} добавлено в очередь.")
        self.event_queue.put(evt)

    def event_processing_loop(self):
        self.logger.debug("Начало цикла обработки событий.")
        loaded_once = False
        while self.processing_enabled:
            self.logger.debug("Загрузка событий из базы данных.")
            events = self.load_events_from_database()
            if events:
                loaded_once = True
            # Пока не загрузили первую пачку — не звоним
            if not loaded_once:
                self.logger.debug("Ещё не загрузили первую партию событий. Ждём...")
                time.sleep(self.repeat_interval.total_seconds())
                continue

            # После того как загрузили, ставим флаг
            if not self.events_loaded_once:
                self.events_loaded_once = True
                self.logger.info("Первая партия событий загружена. Можно инициировать звонки.")

            for e in events:
                if not self.processing_enabled:
                    break
                self.enqueue_event(e)
                self.try_process_events()

            self.logger.debug(f"Цикл завершен. Ждем {self.repeat_interval.total_seconds()} сек.")
            time.sleep(self.repeat_interval.total_seconds())

        self.logger.debug("Цикл обработки событий завершен.")

    def try_process_events(self):
        while (self.processing_enabled
               and self.events_loaded_once
               and not self.event_queue.empty()
               and len(self.futures) < self.max_concurrent_events):
            evt = self.event_queue.get()
            fut = self.executor.submit(self.process_event, evt)
            self.futures.add(fut)
            fut.add_done_callback(self.futures.discard)
            self.logger.debug(f"Обработка события {evt['event_id']} начата.")

    def load_events_from_database(self):
        if not self.event_codes:
            self.logger.warning("Список кодов событий пуст.")
            return []
        database_name = self.config.get('Database', 'database', fallback='Pult4DB')
        placeholders = ', '.join(['%s'] * len(self.event_codes))
        sql = f"""
        SELECT a.Panel_id, a.Event_id, a.Code, a.TimeEvent, 
               COALESCE(d.address, '') as address, 
               d.CompanyName,
               a.StateEvent
        FROM {database_name}.dbo.Temp a
        LEFT JOIN {database_name}.dbo.Panel b ON a.Panel_id = b.Panel_id
        LEFT JOIN {database_name}.dbo.Groups c ON c.Panel_id = b.Panel_id
        LEFT JOIN {database_name}.dbo.Company d ON d.ID = c.CompanyID
        WHERE a.Code IN ({placeholders}) AND a.StateEvent=0
        """
        try:
            rows = self.db_connector.fetchall(sql, self.event_codes)
            self.logger.debug(f"Загружено {len(rows)} событий.")
            out = []
            for row in rows:
                out.append({
                    'panel_id': row['Panel_id'],
                    'event_id': row['Event_id'],
                    'code': row['Code'],
                    'time_event': row['TimeEvent'],
                    'address': row['address'],
                    'company_name': row['CompanyName'],
                    'state_event': row['StateEvent']
                })
            return out
        except Exception as e:
            self.logger.error(f"Ошибка при загрузке событий: {e}")
            return []

    def process_event(self, event):
        """
        Основная логика:
         - проверяем паузу
         - ставим StateEvent=1
         - синтез, обзвон
        """
        self.logger.debug(f"Начата обработка события {event['event_id']}.")
        if not self.processing_enabled:
            return

        # Здесь не делаем лишних проверок, т.к. уже есть event_loaded_once
        panel_id = event['panel_id']
        event_id = event['event_id']

        if not self.can_process_panel(panel_id):
            self.logger.info(f"Событие {event_id} (panel_id={panel_id}) пропущено (период).")
            return

        self.update_event_status(panel_id, event_id, 1)
        with self.lock:
            self.active_events[panel_id] = datetime.now()

        self.handle_event_logic(event)

    def can_process_panel(self, panel_id):
        now = datetime.now()
        with self.lock:
            last_time = self.active_events.get(panel_id)
        if not last_time:
            return True
        if now.date() == last_time.date():
            return False
        diff_hours = (now - last_time).total_seconds() / 3600.0
        if diff_hours < 4.0:
            return False
        return True

    def update_event_status(self, panel_id, event_id, new_state):
        sql = """UPDATE dbo.Temp SET StateEvent=%s WHERE Panel_id=%s AND Event_id=%s"""
        try:
            rows = self.db_connector.execute(sql, (new_state, panel_id, event_id))
            if new_state == 1:
                self.db_connector.commit()
            if rows == 0:
                self.logger.warning(f"Не обновлено событие {event_id}.")
            else:
                self.logger.debug(f"Событие {event_id} -> StateEvent={new_state}.")
        except Exception as e:
            self.logger.error(f"Ошибка update_event_status: {e}")

    def handle_event_logic(self, event):
        panel_id = event['panel_id']
        event_id = event['event_id']
        event_code = event.get('code')
        address = event.get('address', '')
        event_time = event.get('time_event')
        company_name = event.get('company_name', '')

        try:
            # Архив
            if not self.create_archive_event(event):
                self.logger.error(f"Не удалось создать запись в архиве {event_id}")
                self.update_event_status(panel_id, event_id, 0)
                return
            self.create_archive_record(event_id, 'Прием на обработку')

            # Синтез
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
                self.logger.error(f"Ошибка синтеза аудио для {event_id}")
                self.update_event_status(panel_id, event_id, 0)
                return

            file_path = audio_files['mp3']
            file_name = os.path.splitext(os.path.basename(file_path))[0]
            self.logger.debug(f"Аудиофайл для {event_id}: {file_path}")

            # Ответственные
            resp = self.get_responsibles(panel_id)
            if not resp:
                self.logger.warning(f"Нет ответственных для {panel_id}. Завершаем.")
                self.finalize_event(panel_id, event_id)
                return

            self.event_responsibles[event_id] = resp
            self.event_call_attempts[event_id] = 0
            self.call_responsibles(event_id, file_name, panel_id, event)

        except Exception as e:
            self.logger.error(f"Ошибка handle_event_logic: {e}")
            self.update_event_status(panel_id, event_id, 0)

    def get_responsibles(self, panel_id):
        sql = """
        SELECT r.ResponsiblesList_id, COALESCE(rt.PhoneNo, '') as PhoneNo,
               rl.Responsible_Name
        FROM dbo.Responsibles r
        LEFT JOIN dbo.ResponsibleTel rt ON rt.ResponsiblesList_id=r.ResponsiblesList_id
        LEFT JOIN dbo.ResponsiblesList rl ON rl.ResponsiblesList_id=r.ResponsiblesList_id
        WHERE r.Panel_id=%s
        ORDER BY r.Responsible_id ASC
        """
        try:
            rows = self.db_connector.fetchall(sql, (panel_id,))
            out = []
            for row in rows:
                out.append({
                    'responsibles_list_id': row['ResponsiblesList_id'],
                    'phone_number': row['PhoneNo'],
                    'responsible_name': row['Responsible_Name']
                })
            self.logger.debug(f"Найдено {len(out)} ответственных для panel_id={panel_id}.")
            return out
        except Exception as e:
            self.logger.error(f"Ошибка get_responsibles({panel_id}): {e}")
            return []

    def call_responsibles(self, event_id, file_name, panel_id, event):
        resp = self.event_responsibles.get(event_id, [])
        attempt = self.event_call_attempts.get(event_id, 0)
        if attempt >= len(resp):
            self.logger.info(f"Все обзвонили, отправляем SMS (event_id={event_id}).")
            if resp:
                self.send_sms_to_responsible(resp[0], event_id, panel_id, event)
            self.finalize_event(panel_id, event_id)
            return

        responsible = resp[attempt]
        phone = responsible.get('phone_number')
        name = responsible.get('responsible_name')
        if not phone:
            self.logger.warning(f"У {name} нет номера. Следующий.")
            self.event_call_attempts[event_id] += 1
            self.call_responsibles(event_id, file_name, panel_id, event)
            return

        phone_to_call = self.test_mode if self.test_phone_number else phone
        if self.test_mode:
            phone_to_call = self.test_phone_number

        self.logger.debug(f"Инициируем звонок на {phone_to_call}, event_id={event_id}")
        action_id = self.call_manager.make_call(phone_to_call, file_name, panel_id)
        if not action_id:
            self.logger.error(f"Не смогли позвонить на {phone_to_call}. Следующий.")
            time.sleep(self.call_delay_seconds)
            self.event_call_attempts[event_id] += 1
            self.call_responsibles(event_id, file_name, panel_id, event)
            return

        self.call_statuses[action_id] = {
            'event_id': event_id,
            'panel_id': panel_id,
            'responsible': responsible,
            'file_name': file_name,
            'event': event
        }

        rep = {
            'Дата и время обработки': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'ID объекта': panel_id,
            'ID события': event_id,
            'Код события': event.get('code'),
            'Время события': event.get('time_event').strftime('%Y-%m-%d %H:%M:%S'),
            'Адрес': event.get('address'),
            'Название компании': event.get('company_name'),
            'Ответственный': name,
            'Номер телефона': phone,
            'Статус': 'Звонок инициирован',
            'Дополнительная информация': f"UniqueID={action_id}"
        }
        self.write_to_report(rep)
        self.logger.info(f"Звонок инициирован: phone={phone_to_call}, event_id={event_id}, action_id={action_id}.")

    def handle_call_event(self, linkedid, status_type, report_data, extra_info=None):
        if status_type == 'CALL_COMPLETED':
            self.logger.info("Звонок принят -> финализация события.")
            self.write_to_report(report_data)
            event_id = report_data.get('ID события')
            panel_id = report_data.get('ID объекта')
            self.finalize_event(panel_id, event_id)

        elif status_type == 'CALL_HANGUP':
            self.logger.info("Звонок неуспешный -> следующий.")
            self.write_to_report(report_data)
            event_id = report_data.get('ID события')
            panel_id = report_data.get('ID объекта')
            time.sleep(self.call_delay_seconds)
            self.event_call_attempts[event_id] += 1

            call_map = None
            for k, v in self.call_statuses.items():
                if v['event_id'] == event_id:
                    call_map = v
                    break
            if call_map:
                self.call_responsibles(event_id, call_map['file_name'], panel_id, call_map['event'])
        else:
            self.logger.warning(f"Неизвестный статус: {status_type}")

        # Проверяем, можем ли взять следующее
        self.try_process_events()

    def finalize_event(self, panel_id, event_id):
        self.update_event_status(panel_id, event_id, 2)
        self.delete_dependent_records(event_id)
        self.delete_event_from_temp(panel_id, event_id)
        self.create_archive_record(event_id, 'Окончание обработки')
        self.logger.info(f"Событие {event_id} завершено (panel_id={panel_id}).")

        if self.parent:
            self.parent.remove_alarm_card(panel_id)

    def delete_dependent_records(self, event_id):
        sql = "DELETE FROM dbo.TempDetails WHERE Event_id=%s"
        try:
            self.db_connector.execute(sql, (event_id,))
            self.db_connector.commit()
            self.logger.debug(f"TempDetails удалены (event_id={event_id}).")
        except Exception as e:
            self.logger.error(f"Ошибка удаления TempDetails: {e}")

    def delete_event_from_temp(self, panel_id, event_id):
        sql = "DELETE FROM dbo.Temp WHERE Panel_id=%s AND Event_id=%s"
        try:
            self.db_connector.execute(sql, (panel_id, event_id))
            self.db_connector.commit()
            self.logger.debug(f"Событие {event_id} удалено из Temp.")
        except Exception as e:
            self.logger.error(f"Ошибка удаления события {event_id} из Temp: {e}")

    def send_sms_to_responsible(self, resp, event_id, panel_id, event):
        phone = resp.get('phone_number')
        name = resp.get('responsible_name')
        if not phone:
            self.logger.warning(f"У {name} нет номера для SMS.")
            return
        phone_to_sms = self.test_phone_number if self.test_mode else phone
        try:
            msg = self.sms_template.format(
                object_id=panel_id,
                event_code=event.get('code'),
                event_time=event.get('time_event').strftime('%Y-%m-%d %H:%M:%S'),
                company_name=event.get('company_name'),
                address=event.get('address')
            )
        except Exception as e:
            self.logger.error(f"Ошибка форматирования SMS: {e}")
            return
        ok = send_http_sms(
            phone_number=phone_to_sms,
            message=msg,
            url=self.sms_url,
            login=self.sms_login,
            password=self.sms_password,
            shortcode=self.sms_shortcode
        )
        if ok:
            self.logger.info(f"SMS отправлено {phone_to_sms}")
            rep = {
                'Дата и время обработки': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                'ID объекта': panel_id,
                'ID события': event_id,
                'Код события': event.get('code'),
                'Время события': event.get('time_event').strftime('%Y-%m-%d %H:%M:%S'),
                'Адрес': event.get('address'),
                'Название компании': event.get('company_name'),
                'Ответственный': name,
                'Номер телефона': phone,
                'Статус': 'SMS отправлено',
                'Дополнительная информация': ''
            }
            self.write_to_report(rep)
        else:
            self.logger.error(f"Не удалось отправить SMS {phone_to_sms}")

    def create_archive_event(self, event):
        if not self.db_connector:
            self.logger.error("db_connector не инициализирован.")
            return False
        date_now = datetime.now()
        table_name = f"{self.config['Database']['database_archives']}.dbo.archive{date_now.strftime('%Y%m')}01"
        check_sql = f"SELECT COUNT(*) as cnt FROM {table_name} WHERE Event_id=%s"
        insert_sql = f"""
        INSERT INTO {table_name} (
            Event_id, Date_Key, Panel_id, Group_, Line, Zone, Code, CodeGroup,
            TimeEvent, Phone, MeterCount, TimeMeterCount, StateEvent,
            Event_Parent_id, Result_Text, BitMask, DeviceEventTime, ResultID
        )
        VALUES (%s, %s, %s, NULL, NULL, NULL, %s, NULL, %s,
                NULL, NULL, NULL, NULL, NULL, NULL, 0, NULL, NULL)
        """
        params = (
            event['event_id'],
            int(date_now.strftime('%Y%m%d')),
            event['panel_id'],
            event['code'],
            event['time_event']
        )
        try:
            res = self.db_connector.fetch_one(check_sql, (event['event_id'],))
            cnt = 0
            if res:
                cnt = res.get('cnt', 0) if isinstance(res, dict) else res[0]
            if cnt > 0:
                self.logger.info(f"Событие {event['event_id']} уже в архиве.")
                return True
            self.db_connector.execute(insert_sql, params)
            self.db_connector.commit()
            self.logger.info(f"Запись в {table_name} создана.")
            return True
        except Exception as e:
            self.db_connector.rollback()
            self.logger.error(f"Ошибка при создании записи в архив: {e}")
            return False

    def create_archive_record(self, event_id, state_name):
        if not self.db_connector:
            self.logger.error("db_connector не инициализирован.")
            return
        date_now = datetime.now()
        table_name = f"{self.config['Database']['database_archives']}.dbo.eventservice{date_now.strftime('%Y%m')}01"
        sql = f"""
        INSERT INTO {table_name} (NameState, Event_id, Computer, OperationTime, Date_Key, PersonName)
        VALUES (%s, %s, %s, %s, %s, %s)
        """
        params = (
            state_name,
            event_id,
            os.environ.get('COMPUTERNAME', 'unknown'),
            datetime.now(),
            int(date_now.strftime('%Y%m%d')),
            'Смена 1.0'
        )
        try:
            self.db_connector.execute(sql, params)
            self.db_connector.commit()
            self.logger.debug(f"Запись в {table_name} для события {event_id}.")
        except Exception as e:
            self.db_connector.rollback()
            self.logger.error(f"Ошибка create_archive_record: {e}")

    def handle_call_event_callback(self, uniqueid, status, call_info, extra_info=None):
        pass

    def stop(self):
        self.stop_processing()
        if self.call_manager:
            self.call_manager.stop()
        if self.synthesizer:
            self.synthesizer.stop_http_server()
        if self.db_connector:
            self.db_connector.disconnect()
        self.logger.info("EventProcessor остановлен.")
