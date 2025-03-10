# Система Мониторинга SMENA

Система SMENA предназначена для мониторинга тревожных событий, обработки событий с использованием базы данных, отправки уведомлений через звонки, SMS и синтез речи.

## Возможности
- Мониторинг событий через подключение к базе данных.
- Уведомление о тревожных событиях с помощью звонков, SMS и голосовых сообщений.
- Интерактивный пользовательский интерфейс на базе PyQt5.
- Интеграция с IP-телефонией (Asterisk).
- Генерация отчётов и архивирование данных.
- Поддержка многозадачности при обработке событий.

## Основные модули
- **alarm_handler.py**: Обработка тревожных событий и преобразование их в формат для отображения.
- **db_connector.py**: Подключение к базе данных Microsoft SQL Server.
- **event_processor.py**: Логика обработки событий и взаимодействие с внешними системами (звонки, SMS, синтез речи).
- **voice_synthesizer.py**: Синтез голосовых сообщений с использованием Yandex.Cloud.
- **monitoring.py**: Модуль мониторинга новых событий в базе данных.
- **call_manager.py**: Инициация звонков через Asterisk и отслеживание их статусов.
- **ui/**: Интерфейс пользователя, включая настройки, отображение тревог и управления событиями.

## Установка
1. Клонируйте репозиторий:
```markdown
   git clone https://github.com/MrJin94/SMENA1.0.git
   ```
2. Установите зависимости:
   ```bash
   pip install -r requirements.txt
   ```
3. Настройте конфигурацию в файле `config.ini`.

## Запуск
1. Убедитесь, что все зависимости установлены, а база данных настроена.
2. Запустите основное приложение:
   ```bash
   python smena.py
   ```

## Настройки
Файл `config.ini` содержит основные параметры конфигурации:
- **YandexCloud**: Настройки для синтеза речи.
- **Database**: Параметры подключения к базе данных.
- **Telephony**: Параметры подключения к IP-телефонии.
- **SMS**: Настройки для отправки SMS.
- **EventProcessing**: Параметры обработки событий.

## Сборка в исполняемый файл
Для сборки в `.exe` используйте PyInstaller:
```bash
pyinstaller --onefile smena.py
```

## Требования
- Python 3.8+
- Microsoft SQL Server
- Asterisk (для IP-телефонии)
- PyQt5
- Yandex.Cloud API

## Лицензия

Проект распространяется под **персональной лицензией**. Использование программного обеспечения возможно только с письменного согласия Правообладателя. Полный текст лицензии доступен в файле [LICENSE](./LICENSE).


## Контакты
Если у вас есть вопросы или предложения, пишите на  [smena@mrjin.pro](mailto:smena@mrjin.pro).

