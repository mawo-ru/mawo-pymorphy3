# Авторство и Upstream-проекты

Этот документ содержит информацию об оригинальных upstream-проектах, которые легли в основу mawo-pymorphy3.

## Upstream-проекты

### Pymorphy3 и Pymorphy2

**mawo-pymorphy3** является форком проекта **pymorphy3**, который, в свою очередь, является продолжением **pymorphy2**.

#### Pymorphy2 - оригинальный проект

- **Оригинальный репозиторий**: https://github.com/pymorphy2/pymorphy2
- **Автор**: Михаил Коробов (Mikhail Korobov) - [@kmike](https://github.com/kmike)
- **Лицензия**: MIT License
- **Академическая публикация**: Korobov M.: Morphological Analyzer and Generator for Russian and Ukrainian Languages // Analysis of Images, Social Networks and Texts, pp 320-332 (2015)

#### Pymorphy3 - обновлённая версия

- **Репозиторий**: https://github.com/no-plagiarism/pymorphy3
- **Мейнтейнеры**: Danylo Halaiko ([@d9nchik](https://github.com/d9nchik)), [@insolor](https://github.com/insolor)
- **Оригинальный автор**: Mikhail Korobov
- **Лицензия**: MIT License
- **Copyright**: Copyright (c) 2022 (продолжение pymorphy2)
- **Форк MAWO**: https://github.com/mawo-ru/mawo-pymorphy3

## Описание оригинальных проектов

### Pymorphy2

Pymorphy2 - это морфологический анализатор и генератор для русского и украинского языков, разработанный Михаилом Коробовым. Проект был основан в начале 2010-х и стал стандартом де-факто для морфологического анализа русского языка.

**Основные особенности**:
- Морфологический анализ (определение части речи, падежа, числа, рода и т.д.)
- Генерация словоформ (склонение, спряжение)
- Работа с словарями OpenCorpora
- Высокая точность анализа

### Pymorphy3

Pymorphy3 - это обновлённая версия pymorphy2, поддерживаемая сообществом после того, как оригинальный проект перестал активно развиваться.

**Основные улучшения**:
- Поддержка Python 3.6+
- Обновлённые зависимости
- Исправления багов
- Совместимость с современными инструментами

### OpenCorpora

Морфологические словари основаны на проекте OpenCorpora:

- **Сайт**: http://opencorpora.org/
- **Лицензия**: CC BY-SA 3.0
- **Описание**: Корпус русского языка с морфологической разметкой

## Улучшения MAWO

Команда MAWO добавила следующие улучшения к upstream-проекту:

- **Компактные DAWG-словари**: ~11МБ против 69МБ XML (снижение на 84%)
- **Offline-first архитектура**: Полная автономная работа без интернета
- **Потокобезопасность**: Thread-safe реализация с паттерном Singleton
- **OpenCorpora 2025**: Самая свежая версия словарей русского языка
- **Быстрая загрузка**: 1-2 секунды с кэшем против 30-60 секунд разбора XML
- **100% совместимость API**: Drop-in replacement для pymorphy2/pymorphy3
- **Современный инструментарий**: Poetry для управления зависимостями
- **Расширенное тестирование**: Дополнительные тесты и примеры
- **Полная типизация**: Type hints для Python 3.10+
- **Улучшенная безопасность**: Опциональная интеграция с certifi

## Соблюдение лицензий

Этот проект полностью соответствует лицензиям оригинальных проектов:

| Компонент | Лицензия | Оригинальные авторские права |
|-----------|---------|------------------------------|
| Pymorphy2 core | MIT | Copyright (c) Mikhail Korobov and contributors |
| Pymorphy3 updates | MIT | Copyright (c) 2022 (продолжение pymorphy2) |
| OpenCorpora словари | CC BY-SA 3.0 | Участники OpenCorpora |
| DAWG-словари | MIT | Mikhail Korobov (оригинальные данные) |

Согласно условиям MIT лицензии:

> The above copyright notice and this permission notice shall be included in all
> copies or substantial portions of the Software.

Оригинальные уведомления об авторских правах сохранены в файле LICENSE и во всех производных файлах, где это применимо.

## Благодарности

Мы глубоко благодарны:

- **Михаилу Коробову** ([@kmike](https://github.com/kmike)) - за создание оригинального проекта pymorphy2 и фундаментальный вклад в обработку русского языка
- **Danylo Halaiko** ([@d9nchik](https://github.com/d9nchik)) и **@insolor** - за поддержку и развитие pymorphy3
- **Всем контрибьюторам** pymorphy2 и pymorphy3:
  - @ivirabyan, @Yuego, @insolor, @Suor, @adamchainz, @BubaVV (pymorphy2)
  - @Andrej730, @ArchiDevil, @BLKSerene, @Kowalski0805, @Vuizur, @valentino-sm (pymorphy3)
- **Участникам OpenCorpora** - за создание и поддержку корпуса русского языка
- **Сообществу Russian NLP** - за использование и развитие этих инструментов

## Академическая цитата

Если вы используете этот проект в научных целях, пожалуйста, цитируйте оригинальную работу:

```
Korobov M.: Morphological Analyzer and Generator for Russian and Ukrainian Languages
// Analysis of Images, Social Networks and Texts, pp 320-332 (2015).
```

## Участие в проекте

При внесении вклада в mawo-pymorphy3, пожалуйста, убедитесь:

1. Все оригинальные уведомления об авторских правах сохранены
2. Новый код должным образом атрибутирован
3. Совместимость с MIT лицензией поддерживается
4. Совместимость с CC BY-SA 3.0 (для словарей OpenCorpora) сохранена
5. Этот файл ATTRIBUTION.md обновляется при значительных изменениях

## Вопросы или замечания

Если вы заметили отсутствующие атрибуции или проблемы с соблюдением лицензий, пожалуйста, откройте issue:
https://github.com/mawo-ru/mawo-pymorphy3/issues

---

**Последнее обновление**: 2025-11-07

Этот файл атрибуции поддерживается для обеспечения соответствия MIT и CC BY-SA 3.0 лицензиям, уважая работу Михаила Коробова, мейнтейнеров pymorphy3 и участников OpenCorpora.
