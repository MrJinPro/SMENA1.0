from PyQt5.QtCore import QThread, pyqtSignal
import pymssql
import configparser
import os
import time
import logging

current_dir = os.path.dirname(os.path.abspath(__file__))
config_path = os.path.abspath(os.path.join(current_dir, 'config.ini'))

class MonitoringThread(QThread):
    alarms_found = pyqtSignal(list)  # Сигнал, передающий список тревог (словарей)

    def __init__(self, db_connector, interval=10):
        super().__init__()
        self.db_connector = db_connector
        self.event_codes = []  # например ['E302', 'E300']
        self.interval = interval
        self.running = True
 
        # Лог
        self.logger = logging.getLogger('monitoring_thread')
        self.logger.setLevel(logging.INFO)
        handler = logging.StreamHandler()
        formatter = logging.Formatter('%(asctime)s - monitoring_thread - %(levelname)s - %(message)s')
        handler.setFormatter(formatter)
        if not self.logger.handlers:
            self.logger.addHandler(handler)

        self.database_name = self.load_database_name_from_config()

    def run(self):
        while self.running:
            self.reload_event_codes()
            if not self.event_codes:
                self.logger.warning("Нет кодов для мониторинга.")
                time.sleep(self.interval)
                continue

            try:
                with self.db_connector.connection.cursor() as cursor:
                    placeholders = ', '.join(['%s'] * len(self.event_codes))
                    query = (
                        f"SELECT a.Panel_id, a.Code, a.TimeEvent, a.StateEvent, a.Event_id, a.Computer, "
                        f"d.CompanyName, d.address, d.UserName, "
                        f"f.Pult_Name, f.Id as Pult_id, "
                        f"(SELECT DISTINCT CAST(Group_id AS VARCHAR(2)) + ':' + CAST(MainGroup AS VARCHAR(1)) + ';' "
                        f" FROM {self.database_name}.dbo.GroupResponse_Group g "
                        f" WHERE g.Panel_id = a.Panel_id FOR XML PATH('')) as Groups, "
                        f"r.ResponsiblesList_id, COALESCE(rt.PhoneNo, 'Номер не найден') as PhoneNo, "
                        f"rl.Responsible_Name, COALESCE(rl.Responsible_Address, 'Незаполнено') as Responsible_Address "
                        f"FROM {self.database_name}.dbo.Temp a "
                        f"LEFT JOIN {self.database_name}.dbo.Panel b ON a.Panel_id = b.Panel_id "
                        f"LEFT JOIN {self.database_name}.dbo.Groups c ON c.Panel_id = b.Panel_id "
                        f"LEFT JOIN {self.database_name}.dbo.Company d ON d.ID = c.CompanyID "
                        f"LEFT JOIN {self.database_name}.dbo.Pults f ON f.Id = b.Pult_id "
                        f"LEFT JOIN {self.database_name}.dbo.Responsibles r ON r.Panel_id = a.Panel_id "
                        f"LEFT JOIN {self.database_name}.dbo.ResponsibleTel rt ON rt.ResponsiblesList_id = r.ResponsiblesList_id "
                        f"LEFT JOIN {self.database_name}.dbo.ResponsiblesList rl ON rl.ResponsiblesList_id = r.ResponsiblesList_id "
                        f"WHERE a.Code IN ({placeholders}) "
                        f"ORDER BY a.Panel_id DESC"
                    )
                    cursor.execute(query, self.event_codes)
                    rows = cursor.fetchall()
                    if rows:
                        alarm_list = []
                        for alarm in rows:
                            state_event = alarm[3]
                            if state_event in (0, 1):
                                alarm_dict = {
                                    'Panel_id': alarm[0],
                                    'Code': alarm[1],
                                    'TimeEvent': alarm[2],
                                    'StateEvent': alarm[3],
                                    'Event_id': alarm[4],
                                    'Computer': alarm[5],
                                    'CompanyName': alarm[6],
                                    'address': alarm[7],
                                    'UserName': alarm[8],
                                    'Pult_Name': alarm[9],
                                    'Pult_id': alarm[10],
                                    'Groups': alarm[11],
                                    'ResponsiblesList_id': alarm[12],
                                    'PhoneNo': alarm[13],
                                    'Responsible_Name': alarm[14],
                                    'Responsible_Address': alarm[15]
                                }
                                alarm_list.append(alarm_dict)
                        if alarm_list:
                            self.alarms_found.emit(alarm_list)
                            self.logger.info(f"Найдено {len(alarm_list)} тревог (StateEvent=0 или 1).")
                        else:
                            self.logger.info("Тревоги не найдены (StateEvent=0 или 1).")
                    else:
                        self.logger.info("Тревоги не найдены (запрос вернул 0 строк).")
            except pymssql.Error as e:
                self.logger.error(f"Ошибка SQL: {e}")
                self.logger.error(f"Текущий запрос вызвал ошибку: {query}")
            except Exception as e:
                self.logger.error(f"Неожиданная ошибка при выполнении запроса: {e}", exc_info=True)

            time.sleep(self.interval)

    def load_event_codes_from_config(self):
        """Считываем [EventCodes] -> codes (E302,E300,...)"""
        config = configparser.ConfigParser()
        if not os.path.exists(config_path):
            self.logger.error(f"Конфиг не найден: {config_path}")
            return []

        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                config.read_file(f)
        except Exception as e:
            self.logger.error(f"Не удалось прочитать config.ini: {e}")
            return []

        codes_str = config.get('EventCodes', 'codes', fallback='')
        if not codes_str:
            self.logger.warning("Не найдены коды событий в [EventCodes].")
            return []
        return [x.strip() for x in codes_str.split(',') if x.strip()]

    def load_database_name_from_config(self):
        """Читаем Database->database или по умолчанию Pult4DB."""
        config = configparser.ConfigParser()
        if not os.path.exists(config_path):
            self.logger.error(f"Config.ini не найден: {config_path}")
            return 'Pult4DB'
        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                config.read_file(f)
        except Exception as e:
            self.logger.error(f"Ошибка чтения config.ini: {e}")
            return 'Pult4DB'
        return config.get('Database', 'database', fallback='Pult4DB')

    def reload_event_codes(self):
        new_codes = self.load_event_codes_from_config()
        if new_codes != self.event_codes:
            self.logger.info(f"Обновлены коды мониторинга: {new_codes}")
            self.event_codes = new_codes
        else:
            self.logger.debug("Коды не изменились.")

    def stop(self):
        self.running = False
        self.wait()
        self.logger.info("Мониторинг остановлен.")
