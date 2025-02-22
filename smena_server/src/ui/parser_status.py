#!/usr/bin/env python3
import os
import time
import ast
import logging
from datetime import datetime

logger = logging.getLogger('parser_status')
logger.setLevel(logging.INFO)
handler = logging.StreamHandler()
handler.setFormatter(logging.Formatter('%(asctime)s - parser_status - %(levelname)s - %(message)s'))
if not logger.handlers:
    logger.addHandler(handler)

class ParserStatus:
    def __init__(self, log_file_path=r"C:\Users\User\Desktop\smena\ami_log.log"):
        """
        :param log_file_path: Путь к файлу логов AMI.
        """
        self.log_file_path = log_file_path

    def wait_for_status(self, action_id, timeout=60):
        """
        Ожидает появления в логах события, соответствующего звонку с данным action_id,
        которое указывает на окончательный статус (DIALSTATUS = 'ANSWER').
        
        Сначала ищется событие OriginateResponse с нужным ActionID для получения UniqueID.
        Затем – событие VarSet с переменной DIALSTATUS и значением ANSWER, относящееся к тому же UniqueID.
        
        :param action_id: сгенерированный в CallManager.make_call, например "originate-1739504444291"
        :param timeout: время ожидания в секундах
        :return: словарь с информацией, например {"status": "ANSWER", "uniqueid": ...}
                 или None, если время ожидания истекло.
        """
        unique_id = None
        start_time = time.time()

        try:
            with open(self.log_file_path, "r", encoding="utf-8") as f:
                # Переходим в конец файла, чтобы обрабатывать только новые записи
                f.seek(0, os.SEEK_END)

                while time.time() - start_time < timeout:
                    line = f.readline()
                    if not line:
                        time.sleep(0.5)
                        continue

                    # Разбиваем строку по разделителю "->" и пытаемся получить словарь
                    try:
                        parts = line.split("->", 1)
                        if len(parts) != 2:
                            continue
                        dict_str = parts[1].strip()
                        # Преобразуем строку в словарь (используем ast.literal_eval для безопасности)
                        event_data = ast.literal_eval(dict_str)
                    except Exception as e:
                        logger.debug(f"Не удалось распарсить строку: {line.strip()} - {e}")
                        continue

                    # Если событие OriginateResponse, ищем соответствие ActionID
                    if "OriginateResponse" in line:
                        event_action_id = event_data.get("ActionID", "")
                        if event_action_id == action_id:
                            # Попытка взять UniqueID (или LinkedID, если UniqueID отсутствует)
                            unique_id = event_data.get("Uniqueid") or event_data.get("Linkedid")
                            if unique_id:
                                logger.info(f"Найдено OriginateResponse для {action_id}: UniqueID={unique_id}")

                    # Если уже получили UniqueID – ищем событие VarSet с DIALSTATUS = 'ANSWER'
                    if unique_id and "VarSet" in line:
                        var_name = event_data.get("Variable", "")
                        var_value = event_data.get("Value", "")
                        event_uid = event_data.get("Uniqueid") or event_data.get("Linkedid")
                        if var_name == "DIALSTATUS" and var_value.upper() == "ANSWER":
                            # Если в событии указан UniqueID, проверяем его соответствие
                            if event_uid and event_uid == unique_id:
                                logger.info(f"Найден статус ANSWER для UniqueID={unique_id}")
                                return {"status": "ANSWER", "uniqueid": unique_id}
                            else:
                                logger.info(f"Найден статус ANSWER (без проверки UniqueID в событии), UniqueID={unique_id}")
                                return {"status": "ANSWER", "uniqueid": unique_id}
                logger.warning(f"Время ожидания статуса для ActionID {action_id} истекло.")
                return None
        except Exception as e:
            logger.error(f"Ошибка при чтении файла логов: {e}")
            return None

