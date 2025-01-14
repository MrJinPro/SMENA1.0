# src/ui/api_server.py
from flask import Flask, jsonify, request
import logging
import configparser
import os

# Импортируем smena_main, который возвращает smena_obj
from smena import smena_main

app = Flask(__name__)

# Относительный путь к конфигу
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(BASE_DIR, 'config.ini')

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("API_Server")

smena_obj = None  

def load_config():
    config = configparser.ConfigParser()
    config.read(CONFIG_FILE, encoding='utf-8')
    return config

def save_config(config):
    with open(CONFIG_FILE, "w", encoding='utf-8') as configfile:
        config.write(configfile)

@app.route('/status', methods=['GET'])
def get_status():
    """
    Возвращает текущее состояние системы:
      {
        "processing": bool,               # включена ли обработка EventProcessor
        "database": "connected"/"disconnected",
        "telephony": "connected"/"disconnected",
        "sms": "connected"/"disconnected"
      }
    """
    global smena_obj
    if smena_obj is None:
        # Если SMENA ещё не инициализировалась
        return jsonify({
            "processing": False,
            "database": "disconnected",
            "telephony": "disconnected",
            "sms": "disconnected"
        }), 200

    # Предполагается, что smena_obj имеет методы:
    # is_db_connected(), is_asterisk_connected(), is_sms_connected(), is_processing_active()
    db_stat = "connected" if smena_obj.is_db_connected() else "disconnected"
    telephony_stat = "connected" if smena_obj.is_asterisk_connected() else "disconnected"
    sms_stat = "connected" if smena_obj.is_sms_connected() else "disconnected"

    processing_active = smena_obj.is_processing_active()

    status = {
        "processing": processing_active,
        "database": db_stat,
        "telephony": telephony_stat,
        "sms": sms_stat
    }
    return jsonify(status), 200

@app.route('/processing', methods=['POST'])
def toggle_processing():
    """
    Управление обработкой событий (EventProcessor) — включение/выключение.
    Принимает JSON: {"enable": true/false}
    """
    global smena_obj
    data = request.json
    if "enable" not in data:
        return jsonify({"error": "Invalid request, 'enable' not found"}), 400

    enable = data["enable"]
    if smena_obj is None:
        logger.error("SMENA объект не инициализирован!")
        return jsonify({"error": "Server is not ready"}), 500

    if enable:
        smena_obj.start_processing()
        logger.info("EventProcessor: start_processing() вызвано.")
    else:
        smena_obj.stop_processing()
        logger.info("EventProcessor: stop_processing() вызвано.")

    status_msg = "enabled" if enable else "disabled"
    return jsonify({"status": f"Processing {status_msg}"}), 200

@app.route('/config/sections', methods=['GET'])
def get_config_sections():
    """
    Возвращает список секций (разделов) из config.ini
    """
    config = load_config()
    return jsonify({"sections": config.sections()}), 200

@app.route('/config/<section>', methods=['GET'])
def get_config_section(section):
    """
    Возвращает ключи/значения конкретной секции из config.ini
    """
    config = load_config()
    if section not in config:
        return jsonify({"error": "Section not found"}), 404
    return jsonify(dict(config[section])), 200

@app.route('/config/<section>', methods=['POST'])
def update_config_section(section):
    """
    Обновляет (или создаёт) секцию config.ini, принимая JSON:
      { "key1": "value1", "key2": "value2" }
    """
    config = load_config()
    if section not in config:
        config.add_section(section)
    data = request.json
    for key, value in data.items():
        config[section][key] = str(value)
    save_config(config)
    logger.info(f"Секция [{section}] обновлена: {data}")
    return jsonify({"status": "Configuration updated"}), 200

def initialize_smena():
    """
    Инициализация smena_obj
    """
    global smena_obj
    smena_obj = smena_main()
