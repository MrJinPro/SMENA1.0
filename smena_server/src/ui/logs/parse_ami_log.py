import re
import os

def parse_ami_log_for_action_id(log_file, target_action_id):
    """
    Ищет в логах AMI (log_file) записи для переданного ActionID,
    затем вычитывает DialStatus (BUSY, ANSWER, NOANSWER, ...) из DialEnd, 
    чтобы определить реальный итог звонка.
    """

    print(f"\n=== parse_ami_log_for_action_id ===")
    print(f"Читаем лог: {log_file}")
    print(f"Целевой ActionID: {target_action_id}")
    print("====================================\n")

    # Словарь: uniqueid -> action_id. Когда видим OriginateResponse, сохраним связь
    uniqueid_to_action_id = {}

    # Это итоговый статус для нужного action_id (пока None)
    final_status = None

    # Шаблоны регулярных выражений:
    orig_regex = r"OriginateResponse.*'ActionID':\s*'([^']+)'.*'Uniqueid':\s*'([^']+)'.*'Response':\s*'([^']+)'"
    dialend_regex = r"DialEnd.*'DestUniqueid':\s*'([^']+)'.*'DialStatus':\s*'([^']+)'"

    print(f"Regex для OriginateResponse:\n {orig_regex}\n")
    print(f"Regex для DialEnd:\n {dialend_regex}\n")

    with open(log_file, 'r', encoding='utf-8') as f:
        line_number = 0
        for line in f:
            line_number += 1

            # Отладочный вывод: смотрим каждую строку
            # (Если лог огромный, можно закомментировать, чтобы не перегружать консоль)
            print(f"[Line {line_number}] {line.strip()}")

            # --- 1) Ищем OriginateResponse
            orig_match = re.search(orig_regex, line)
            if orig_match:
                action_id = orig_match.group(1)
                uniqueid = orig_match.group(2)
                response = orig_match.group(3).lower()

                print(f"  -> Нашли OriginateResponse на строке {line_number}:")
                print(f"     ActionID = {action_id}, Uniqueid = {uniqueid}, Response = {response}")

                if action_id == target_action_id:
                    uniqueid_to_action_id[uniqueid] = action_id
                    print(f"     * Это наш ActionID ({target_action_id}), сохранили связь uniqueid->action_id.")

                # Если 'failure', теоретически можно сразу финализировать как 'FAILED'
                # Но чаще мы ждём DialEnd

            # --- 2) Ищем DialEnd c DialStatus
            dialend_match = re.search(dialend_regex, line)
            if dialend_match:
                dest_uniqueid = dialend_match.group(1)
                raw_status = dialend_match.group(2)
                dialstatus = normalize_dialstatus(raw_status)

                print(f"  -> Нашли DialEnd на строке {line_number}:")
                print(f"     DestUniqueid = {dest_uniqueid}, DialStatus = {raw_status} ( => {dialstatus} )")

                if dest_uniqueid in uniqueid_to_action_id:
                    # проверяем, тот ли action_id
                    found_action_id = uniqueid_to_action_id[dest_uniqueid]
                    print(f"     * Uniqueid={dest_uniqueid} соответствует ActionID={found_action_id}")
                    if found_action_id == target_action_id:
                        final_status = dialstatus
                        print(f"     * Финальный статус для {target_action_id} = {dialstatus}")

    print("\n=== Результат ===")
    if final_status:
        print(f"Финальный статус для {target_action_id}: {final_status}")
    else:
        print(f"Не найден финальный статус для {target_action_id} (или звонок не завершён).")
    print("====================================\n")

    return final_status

def normalize_dialstatus(raw_status):
    dial_map = {
        'ANSWER': 'ANSWERED',
        'BUSY': 'BUSY',
        'NOANSWER': 'NO ANSWER',
        'NO ANSWER': 'NO ANSWER',
        'FAILED': 'FAILED',
        'CANCEL': 'CANCELED',
        'CANCELED': 'CANCELED',
        'ANSWERED': 'ANSWERED',
        # при желании 'BRIDGED': 'BRIDGED'
    }
    return dial_map.get(raw_status.upper(), raw_status.upper())

if __name__ == "__main__":
    # Путь к логу
    log_file = os.path.join("smena_server", "src", "ui", "logs", "ami_log.log")

    # Искомый ActionID
    target_action_id = "originate-1739925636924"

    parse_ami_log_for_action_id(log_file, target_action_id)
