# Security Policy

## Supported Versions

Мы поддерживаем следующие версии mawo-pymorphy3:

| Version | Supported          |
| ------- | ------------------ |
| 1.0.x   | :white_check_mark: |
| < 1.0   | :x:                |

## Reporting a Vulnerability

Если вы обнаружили уязвимость в безопасности, пожалуйста:

1. **НЕ создавайте публичный Issue** - это может подвергнуть риску других пользователей
2. **Отправьте email** на team@mawo.ru с темой "SECURITY: mawo-pymorphy3"
3. **Или используйте** [GitHub Private Security Advisories](https://github.com/mawo-ru/mawo-pymorphy3/security/advisories)

### Что включить в отчет:

- Описание уязвимости
- Шаги для воспроизведения
- Потенциальное влияние
- Предложения по исправлению (если есть)

### Что ожидать:

- **Подтверждение получения** в течение 48 часов
- **Оценка серьезности** в течение 7 дней
- **Исправление** в течение 30 дней для критичных уязвимостей

## Security Best Practices

При использовании mawo-pymorphy3:

1. **Установка с проверкой**:
   ```bash
   pip install mawo-pymorphy3 --require-hashes
   ```

2. **Используйте defusedxml** (рекомендуется):
   ```bash
   pip install mawo-pymorphy3[security]
   ```

3. **Проверяйте контрольные суммы** для больших данных:
   ```bash
   wget https://github.com/mawo-ru/mawo-nlp-data/releases/download/v1.0.0/checksums.txt
   sha256sum -c checksums.txt
   ```

## Known Security Considerations

### XML Parsing
- Библиотека парсит XML файлы OpenCorpora
- Используется `defusedxml` когда доступен (рекомендуется)
- Fallback на стандартный `xml.etree.ElementTree` с ограничением размера файла

### Pickle Cache
- Используется для кэширования словарей
- Загружается только из локальных файлов, созданных библиотекой
- Ограничение размера: 500MB максимум

### User Input
- Библиотека **не выполняет** код из пользовательского ввода
- Безопасна для обработки пользовательского текста

## Security Updates

Обновления безопасности публикуются через:
- GitHub Security Advisories
- PyPI yanked releases (для критичных проблем)
- Email уведомления для зарегистрированных пользователей

## Credits

Мы благодарим исследователей безопасности, которые ответственно раскрывают уязвимости.

Список благодарностей будет опубликован здесь.
