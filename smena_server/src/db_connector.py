# db_connector.py

import pymssql
import threading
from PyQt5.QtWidgets import QMessageBox
import logging

class DBConnector:
    """Класс для управления соединением с базой данных."""

    def __init__(self, config, parent=None):
        """
        Инициализирует соединение с базой данных.

        :param config: Объект configparser.ConfigParser с настройками.
        :param parent: Родительское окно для отображения сообщений об ошибках (опционально).
        """
        self.server = config.get('Database', 'server', fallback='127.0.0.1')
        self.user = config.get('Database', 'user', fallback='sa')
        self.password = config.get('Database', 'password', fallback='1')
        self.database = config.get('Database', 'database', fallback='Pult4DB')
        self.connection = None
        self.lock = threading.Lock()  # Для обеспечения потокобезопасности

        # Настройка логирования
        self.logger = logging.getLogger(self.__class__.__name__)
        self.logger.setLevel(logging.DEBUG)
        handler = logging.StreamHandler()
        formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
        handler.setFormatter(formatter)
        if not self.logger.handlers:
            self.logger.addHandler(handler)

        self.connect(parent)  # Подключаемся при инициализации

    def connect(self, parent=None):
        """Подключается к базе данных и возвращает статус подключения."""
        try:
            # Подключаемся к базе данных
            self.connection = pymssql.connect(
                server=self.server,
                user=self.user,
                password=self.password,
                database=self.database,
                autocommit=False  # Управление транзакциями вручную
            )
            self.logger.info("Успешно подключено к базе данных.")
            return True

        except pymssql.InterfaceError as e:
            if parent:
                QMessageBox.critical(parent, "Ошибка подключения", f"Не удалось подключиться к серверу базы данных: {e}")
            self.logger.error(f"InterfaceError: {e}")
            return False

        except pymssql.DatabaseError as e:
            if parent:
                QMessageBox.critical(parent, "Ошибка базы данных", f"Ошибка базы данных: {e}")
            self.logger.error(f"DatabaseError: {e}")
            return False

    def disconnect(self):
        """Закрывает подключение к базе данных."""
        if self.connection:
            self.connection.close()
            self.logger.info("Соединение с базой данных закрыто.")

    def execute(self, sql, params=None, commit=True):
        """
        Выполняет SQL-запрос с параметрами.

        :param sql: Строка SQL-запроса.
        :param params: Кортеж или список параметров для запроса.
        :param commit: Флаг, указывающий, нужно ли выполнять commit после запроса.
        :return: Список результатов для SELECT-запросов или количество затронутых строк для других запросов.
        """
        with self.lock:
            try:
                with self.connection.cursor() as cursor:
                    self.logger.debug(f"Выполнение запроса: {sql} с параметрами: {params}")
                    cursor.execute(sql, params)

                    # Определяем тип запроса
                    if sql.strip().upper().startswith("SELECT"):
                        columns = [desc[0] for desc in cursor.description]
                        results = [dict(zip(columns, row)) for row in cursor.fetchall()]
                        self.logger.debug(f"Получено результатов: {len(results)}")
                        return results
                    else:
                        rowcount = cursor.rowcount
                        if commit:
                            self.connection.commit()
                            self.logger.debug("Транзакция зафиксирована.")
                        return rowcount

            except pymssql.DatabaseError as e:
                self.connection.rollback()
                self.logger.error(f"Ошибка выполнения SQL-запроса: {e}. Транзакция откатилась.")
                raise e  # Повторно выбрасываем исключение для обработки выше

    def fetchall(self, sql, params=None):
        """
        Выполняет SQL-запрос и возвращает все результаты в виде списка словарей.

        :param sql: Строка SQL-запроса.
        :param params: Кортеж или список параметров для запроса.
        :return: Список словарей с результатами.
        """
        return self.execute(sql, params, commit=False)

    def fetch_one(self, sql, params=None):
        """
        Выполняет SQL-запрос и возвращает один результат в виде словаря.

        :param sql: Строка SQL-запроса.
        :param params: Кортеж или список параметров для запроса.
        :return: Словарь с одним результатом или None.
        """
        with self.lock:
            try:
                with self.connection.cursor() as cursor:
                    self.logger.debug(f"Выполнение запроса для одного результата: {sql} с параметрами: {params}")
                    cursor.execute(sql, params)
                    row = cursor.fetchone()
                    if row:
                        columns = [desc[0] for desc in cursor.description]
                        result = dict(zip(columns, row))
                        self.logger.debug(f"Получен один результат: {result}")
                        return result
                    else:
                        self.logger.debug("Результат запроса пуст.")
                        return None
            except pymssql.DatabaseError as e:
                self.connection.rollback()
                self.logger.error(f"Ошибка выполнения SQL-запроса: {e}. Транзакция откатилась.")
                raise e

    def commit(self):
        """Выполняет commit текущей транзакции."""
        with self.lock:
            try:
                self.connection.commit()
                self.logger.debug("Транзакция зафиксирована.")
            except pymssql.DatabaseError as e:
                self.connection.rollback()
                self.logger.error(f"Ошибка при выполнении commit: {e}. Транзакция откатилась.")
                raise e

    def rollback(self):
        """Выполняет откат текущей транзакции."""
        with self.lock:
            try:
                self.connection.rollback()
                self.logger.debug("Транзакция откатилась.")
            except pymssql.DatabaseError as e:
                self.logger.error(f"Ошибка при выполнении rollback: {e}")
                raise e
