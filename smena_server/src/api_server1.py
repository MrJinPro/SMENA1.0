from fastapi import FastAPI, HTTPException, Depends, Header
from pydantic import BaseModel
from db_connector import DBConnector
from ui.call_manager import CallManager
from ui.sms_manager import send_http_sms
import logging
import configparser
import os

# Загрузка конфигурации
config_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "ui", "config.ini"))
config = configparser.ConfigParser()
if os.path.exists(config_path):
    config.read(config_path, encoding='utf-8')
else:
    raise FileNotFoundError(f"Конфигурационный файл {config_path} не найден")

# Проверка наличия секции Asterisk в конфиге
if 'Asterisk' not in config:
    raise KeyError("Секция 'Asterisk' отсутствует в конфигурационном файле")

db_connector = DBConnector(config)
call_manager = CallManager(config, callback=None)

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("api_server")

app = FastAPI(title="SMENA API", description="API для управления тревогами, вызовами, SMS и отчетностью")

# Разрешенные клиенты (например, только локальная сеть)
ALLOWED_CLIENTS = ["192.168.1.100", "192.168.1.101", "192.168.1.102"]  # Укажите IP-адреса операторов
API_KEY = "secure-api-key"  # API-ключ для авторизации

# Проверка API-ключа
def verify_api_key(api_key: str = Header(...)):
    if api_key != API_KEY:
        raise HTTPException(status_code=403, detail="Неверный API-ключ")

@app.get("/settings/{category}", dependencies=[Depends(verify_api_key)])
def get_settings(category: str):
    """Получение настроек по категории."""
    if category in config:
        return dict(config[category])
    raise HTTPException(status_code=404, detail="Категория не найдена")

@app.post("/settings/{category}", dependencies=[Depends(verify_api_key)])
def update_settings(category: str, update: BaseModel):
    """Обновление настроек."""
    if category in config:
        config[category][update.key] = update.value
        with open(config_path, 'w', encoding='utf-8') as configfile:
            config.write(configfile)
        return {"status": "success", "message": "Настройки обновлены"}
    raise HTTPException(status_code=404, detail="Категория не найдена")

@app.get("/alarms", dependencies=[Depends(verify_api_key)])
def get_alarms():
    """Получение списка тревог."""
    query = "SELECT * FROM Temp WHERE StateEvent = 0"
    alarms = db_connector.fetchall(query)
    return alarms

@app.post("/alarms/{alarm_id}/acknowledge", dependencies=[Depends(verify_api_key)])
def acknowledge_alarm(alarm_id: int):
    """Подтверждение тревоги."""
    query = "UPDATE Temp SET StateEvent = 1 WHERE Event_id = %s"
    db_connector.execute(query, (alarm_id,))
    db_connector.commit()
    return {"status": "success", "message": "Тревога подтверждена"}

@app.post("/call/{phone_number}", dependencies=[Depends(verify_api_key)])
def initiate_call(phone_number: str, file_name: str):
    """Инициирование звонка."""
    action_id = call_manager.make_call(phone_number, file_name)
    if action_id:
        return {"status": "success", "action_id": action_id}
    raise HTTPException(status_code=500, detail="Ошибка при выполнении вызова")

@app.post("/sms/{phone_number}", dependencies=[Depends(verify_api_key)])
def send_sms(phone_number: str, message: str):
    """Отправка SMS."""
    success = send_http_sms(
        phone_number, message, 
        config['SMS']['url'], 
        config['SMS']['login'], 
        config['SMS']['password'], 
        config['SMS']['shortcode']
    )
    if success:
        return {"status": "success", "message": "SMS отправлено"}
    raise HTTPException(status_code=500, detail="Ошибка при отправке SMS")

@app.get("/logs", dependencies=[Depends(verify_api_key)])
def get_logs():
    """Получение логов системы."""
    log_file = "logs/smena.log"
    if os.path.exists(log_file):
        with open(log_file, "r", encoding="utf-8") as f:
            logs = f.readlines()
        return {"logs": logs[-50:]}
    raise HTTPException(status_code=404, detail="Лог-файл не найден")

@app.get("/reports", dependencies=[Depends(verify_api_key)])
def get_reports():
    """Получение списка отчетов."""
    reports_dir = "otcet"
    if not os.path.exists(reports_dir):
        return {"reports": []}
    reports = os.listdir(reports_dir)
    return {"reports": reports}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8008)
