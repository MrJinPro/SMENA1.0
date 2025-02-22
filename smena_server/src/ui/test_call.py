import logging
import time
from asterisk.ami import AMIClient

logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s [%(levelname)s] %(name)s - %(message)s'
)
logger = logging.getLogger(__name__)

class AsteriskCallStatus:
    def __init__(self, host, port, username, secret):
        self.host = host
        self.port = port
        self.username = username
        self.secret = secret

        self.client = None
        self.calls = {}  # Храним статусы по UniqueID или LinkedID

    def connect(self):
        # Подключаемся к AMI
        self.client = AMIClient(address=self.host, port=self.port)
        self.client.connect()
        self.client.login(username=self.username, secret=self.secret)
        logger.info("Успешное подключение к AMI")

        # Подписываемся на ВСЕ события (event_filter=None)
        self.client.add_event_listener(self.handle_event, event_filter=None)

    def handle_event(self, event, **kwargs):
        """
        Ловим события:
          - Dial (SubEvent=Begin / End)
          - Hangup
          - VarSet(DIALSTATUS)
        и выводим в лог.
        """
        event_name = event.name
        uniqueid = event.get('Uniqueid')
        linkedid = event.get('Linkedid')  # Часто общий идентификатор звонка

        # Для удобства берём linkedid, если он есть, иначе uniqueid
        call_id = linkedid if linkedid else uniqueid

        logger.debug(f"Событие: {event_name}, UniqueID={uniqueid}, LinkedID={linkedid}, поля={dict(event)}")

        if event_name == "Dial":
            subevent = event.get('SubEvent')
            if subevent == "Begin":
                # Начало Dial()
                dialstring = event.get('DialString')
                logger.info(f"[{call_id}] Dial Begin: DialString={dialstring}")
                self._init_call(call_id)
                self.calls[call_id]['status'] = 'DIALING'
            elif subevent == "End":
                # Завершение Dial() (прикол: здесь может быть DialStatus)
                dialstatus = event.get('DialStatus')
                logger.info(f"[{call_id}] Dial End: DialStatus={dialstatus}")
                self._init_call(call_id)
                if dialstatus:
                    self.calls[call_id]['dialstatus'] = dialstatus

        elif event_name == "Hangup":
            cause_txt = event.get('Cause-txt')
            channel = event.get('Channel')
            logger.info(f"[{call_id}] Hangup: Channel={channel}, Cause={cause_txt}")
            self._init_call(call_id)
            self.calls[call_id]['hangup_cause'] = cause_txt

        elif event_name == "VarSet":
            # Ловим момент, когда в Asterisk устанавливается DIALSTATUS
            variable = event.get('Variable')
            value = event.get('Value')
            if variable == "DIALSTATUS":
                logger.info(f"[{call_id}] VarSet DIALSTATUS={value}")
                self._init_call(call_id)
                self.calls[call_id]['dialstatus'] = value

        # Можно добавить OriginateResponse, Bridge и т.д. при необходимости

    def _init_call(self, call_id):
        """Помогает хранить в словаре calls информацию по вызовам."""
        if call_id not in self.calls:
            self.calls[call_id] = {
                'status': None,
                'dialstatus': None,
                'hangup_cause': None
            }

    def run(self):
        """
        Блокирующий цикл: просто ждём события.
        Останавливать через Ctrl+C.
        """
        logger.info("Ожидание событий (Ctrl+C для выхода).")
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            logger.info("Завершаем...")

        if self.client:
            self.client.logoff()
            logger.info("Отключились от AMI")

if __name__ == "__main__":
    # Поставь свои реквизиты
    HOST = "192.168.3.20"
    PORT = 5038
    USER = "voicebot"
    PASS = "7DNPSgV7q3EH"

    ami = AsteriskCallStatus(HOST, PORT, USER, PASS)
    ami.connect()
    ami.run()