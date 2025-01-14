class AlarmHandler:
    def __init__(self, db_connector):
        self.db_connector = db_connector

    def process_alarm(self, alarm):
        """Обрабатывает отдельную тревогу и возвращает информацию для отображения."""
        try:
            # Просто собираем поля в dict. 
            alarm_info = {
                'Panel_id': alarm['Panel_id'],
                'Code': alarm['Code'],
                'TimeEvent': alarm['TimeEvent'],
                'StateEvent': alarm['StateEvent'],
                'Event_id': alarm['Event_id'],
                'CompanyName': alarm['CompanyName'],
                'address': alarm['address'],
                'UserName': alarm['UserName'],
                'Pult_Name': alarm['Pult_Name'],
                'Pult_id': alarm['Pult_id'],
                'Groups': alarm['Groups'],
                'ResponsiblesList_id': alarm['ResponsiblesList_id'],
                'PhoneNo': alarm.get('PhoneNo', 'N/A'),
                'Responsible_Name': alarm.get('Responsible_Name', 'N/A'),
                'Responsible_Address': alarm.get('Responsible_Address', 'N/A'),
            }
            return alarm_info
        except KeyError as e:
            print(f"Ошибка: Отсутствует ключ {e} в тревоге: {alarm}")
            return None
