import os
import sys
import socket

def get_local_ip():
    """
    Определяет локальный IP-адрес машины.
    Возвращает строку с IP-адресом.
    """
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            # Не обязательно должен быть доступен
            s.connect(('10.255.255.255', 1))
            IP = s.getsockname()[0]
    except Exception:
        IP = '127.0.0.1'
    return IP 

def resource_path(relative_path):
    """Получает абсолютный путь к ресурсу, учитывая сборку приложения."""
    try:
        # PyInstaller создает временную папку и помещает туда ресурсы
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")

    return os.path.join(base_path, relative_path)
