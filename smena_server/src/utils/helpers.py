import smpplib.client
import smpplib.consts

client = smpplib.client.Client('193.232.44.124', 3700)

client.connect()

try:
    if client.state != 'BOUND_TRX':  # Проверка состояния привязки
        client.bind_transceiver(
            system_id='sm1000726903',
            password='iNwisY7N',
            system_type='SMPP',
            addr_ton=smpplib.consts.SMPP_TON_INTL,
            addr_npi=smpplib.consts.SMPP_NPI_ISDN,
            address_range='ZD_oharona'
        )
        print("Подключение успешно!")
    else:
        print("Уже привязан.")
except Exception as e:
    print(f"Ошибка привязки: {e}")
finally:
    # Проверка, привязан ли клиент перед разрывом
    if client.state == 'BOUND_TRX':
        client.unbind()
    client.disconnect()
