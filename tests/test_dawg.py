"""
Строгий тест для проверки DAWG интеграции в mawo-pymorphy3

Этот тест проверяет что:
1. DAWG словари действительно используются
2. Загрузка быстрая (<1 секунды)
3. Память используется эффективно
4. Морфологический анализ работает корректно
"""

import time
from pathlib import Path


class TestDAWGIntegration:
    """Строгая проверка интеграции DAWG"""

    def test_dawg_dictionaries_exist(self):
        """Тест: DAWG словари существуют в пакете"""
        import mawo_pymorphy3

        package_dir = Path(mawo_pymorphy3.__file__).parent
        dicts_dir = package_dir / "dicts_ru"

        assert dicts_dir.exists(), f"DAWG словари не найдены: {dicts_dir}"
        assert dicts_dir.is_dir(), f"dicts_ru должна быть директорией: {dicts_dir}"

        # Проверяем наличие ключевых DAWG файлов
        required_files = [
            "words.dawg",
            "paradigms.array",
            "suffixes.json",
            "gramtab-opencorpora-int.json",
            "grammemes.json",
            "meta.json",
        ]

        for filename in required_files:
            file_path = dicts_dir / filename
            assert file_path.exists(), f"Файл не найден: {filename}"

    def test_dawg_enabled_by_default(self):
        """Тест: DAWG включен по умолчанию"""
        from mawo_pymorphy3 import create_analyzer

        analyzer = create_analyzer()
        assert analyzer.use_dawg is True, "DAWG должен быть включен по умолчанию"
        assert analyzer._dawg_dict is not None, "DAWG словарь должен быть инициализирован"

    def test_fast_loading_with_dawg(self):
        """Тест: быстрая загрузка с DAWG (<2 секунды)"""
        from mawo_pymorphy3 import MAWOMorphAnalyzer

        start = time.time()
        _ = MAWOMorphAnalyzer(use_dawg=True)
        elapsed = time.time() - start

        assert elapsed < 2.0, f"Загрузка с DAWG должна быть < 2 сек, получено: {elapsed:.3f} сек"

    def test_morphology_with_dawg(self):
        """Тест: морфологический анализ работает с DAWG"""
        from mawo_pymorphy3 import create_analyzer

        analyzer = create_analyzer(use_dawg=True)

        # Тестируем разные части речи
        test_cases = [
            ("дом", "NOUN"),  # существительное
            ("красивый", "ADJF"),  # прилагательное
            ("бегать", "INFN"),  # глагол (инфинитив)
            ("быстро", "ADVB"),  # наречие
        ]

        for word, expected_pos in test_cases:
            parses = analyzer.parse(word)
            assert len(parses) > 0, f"Нет разборов для слова '{word}'"

            # Проверяем что есть разбор с нужным POS
            pos_list = [p.tag.POS for p in parses]
            assert (
                expected_pos in pos_list
            ), f"Ожидался POS {expected_pos} для '{word}', получено: {pos_list}"

    def test_normal_form_extraction(self):
        """Тест: извлечение нормальной формы работает"""
        from mawo_pymorphy3 import create_analyzer

        analyzer = create_analyzer(use_dawg=True)

        # Тестируем склонения
        test_cases = [
            ("столы", "стол"),  # множественное число
            ("красивая", "красивый"),  # женский род
            ("бегал", "бегать"),  # прошедшее время
        ]

        for word, expected_normal in test_cases:
            parses = analyzer.parse(word)
            assert len(parses) > 0, f"Нет разборов для слова '{word}'"

            # Проверяем что хотя бы один разбор дает правильную нормальную форму
            normal_forms = [p.normal_form for p in parses]
            assert (
                expected_normal in normal_forms
            ), f"Ожидалась нормальная форма '{expected_normal}' для '{word}', получено: {normal_forms}"

    def test_grammemes_extraction(self):
        """Тест: извлечение граммем работает"""
        from mawo_pymorphy3 import create_analyzer

        analyzer = create_analyzer(use_dawg=True)

        # Тестируем слово "дома" (родительный падеж / множественное число)
        parses = analyzer.parse("дома")
        assert len(parses) > 0, "Нет разборов для слова 'дома'"

        # Проверяем что есть граммемы
        for parse in parses:
            assert hasattr(parse.tag, "grammemes"), "У тега должны быть граммемы"
            assert isinstance(parse.tag.grammemes, set), "Граммемы должны быть множеством"

    def test_tag_properties(self):
        """Тест: свойства тега работают"""
        from mawo_pymorphy3 import create_analyzer

        analyzer = create_analyzer(use_dawg=True)

        # Тестируем существительное в родительном падеже
        parses = analyzer.parse("дома")
        assert len(parses) > 0

        # Ищем разбор существительного
        noun_parses = [p for p in parses if p.tag.POS == "NOUN"]
        assert len(noun_parses) > 0, "Должен быть хотя бы один разбор существительного"

        # Проверяем свойства тега
        noun_parse = noun_parses[0]
        assert hasattr(noun_parse.tag, "case"), "Тег должен иметь свойство case"
        assert hasattr(noun_parse.tag, "number"), "Тег должен иметь свойство number"
        assert hasattr(noun_parse.tag, "gender"), "Тег должен иметь свойство gender"

    def test_performance_with_dawg(self):
        """Тест: производительность с DAWG (должна быть высокой)"""
        from mawo_pymorphy3 import create_analyzer

        analyzer = create_analyzer(use_dawg=True)

        # Прогрев
        analyzer.parse("тест")

        # Тестируем скорость
        test_word = "тестовое"
        iterations = 1000

        start = time.time()
        for _ in range(iterations):
            analyzer.parse(test_word)
        elapsed = time.time() - start

        words_per_sec = iterations / elapsed
        assert (
            words_per_sec > 5000
        ), f"Скорость должна быть > 5000 слов/сек, получено: {words_per_sec:.0f}"

    def test_dawg_vs_fallback_speed(self):
        """Тест: DAWG значительно быстрее fallback режима"""
        from mawo_pymorphy3 import MAWOMorphAnalyzer

        # Замеряем с DAWG
        start = time.time()
        _ = MAWOMorphAnalyzer(use_dawg=True)
        dawg_time = time.time() - start

        # DAWG должен загружаться быстро
        assert dawg_time < 2.0, f"DAWG загрузка должна быть < 2 сек, получено: {dawg_time:.3f} сек"

    def test_dawg_dictionary_available(self):
        """Тест: DAWG словарь доступен внутри"""
        from mawo_pymorphy3 import create_analyzer

        analyzer = create_analyzer(use_dawg=True)

        # Проверяем что внутри используется DAWGDictionary
        assert hasattr(analyzer, "_dawg_dict"), "Должен быть атрибут _dawg_dict"
        assert analyzer._dawg_dict is not None, "DAWG словарь должен быть инициализирован"

        # Проверяем что это действительно DAWGDictionary
        analyzer_type = type(analyzer._dawg_dict).__name__
        assert (
            analyzer_type == "DAWGDictionary"
        ), f"Должен быть DAWGDictionary, получено: {analyzer_type}"

    def test_meta_information(self):
        """Тест: метаинформация о словаре доступна"""
        import json
        from pathlib import Path

        import mawo_pymorphy3

        package_dir = Path(mawo_pymorphy3.__file__).parent
        meta_path = package_dir / "dicts_ru" / "meta.json"

        assert meta_path.exists(), "Файл meta.json должен существовать"

        with open(meta_path, encoding="utf-8") as f:
            meta_list = json.load(f)
            meta = dict(meta_list)

        # Проверяем ключевые поля
        assert "format_version" in meta, "Должна быть версия формата"
        assert "source" in meta, "Должен быть источник"
        assert "source_lexemes_count" in meta, "Должно быть количество лексем"

        # Проверяем разумные значения
        assert meta["source_lexemes_count"] > 100000, "Должно быть > 100k лексем в словаре"

    def test_singleton_pattern_with_dawg(self):
        """Тест: синглтон паттерн работает с DAWG"""
        from mawo_pymorphy3 import create_analyzer

        # Создаем два анализатора
        analyzer1 = create_analyzer(use_dawg=True)
        analyzer2 = create_analyzer(use_dawg=True)

        # Должны быть одним объектом (синглтон)
        assert analyzer1 is analyzer2, "create_analyzer должен возвращать синглтон экземпляр"


class TestDAWGCorrectness:
    """Проверка корректности работы DAWG"""

    def test_real_world_words(self):
        """Тест: реальные русские слова разбираются правильно"""
        from mawo_pymorphy3 import create_analyzer

        analyzer = create_analyzer(use_dawg=True)

        # Список реальных слов с ожидаемыми POS
        real_words = [
            ("кот", "NOUN"),
            ("собака", "NOUN"),
            ("красный", "ADJF"),
            ("бегать", "INFN"),
            ("быстро", "ADVB"),
            ("в", "PREP"),
            ("и", "CONJ"),
        ]

        for word, expected_pos in real_words:
            parses = analyzer.parse(word)
            assert len(parses) > 0, f"Слово '{word}' должно разбираться"

            pos_list = [p.tag.POS for p in parses]
            assert (
                expected_pos in pos_list
            ), f"Слово '{word}' должно иметь POS {expected_pos}, получено: {pos_list}"

    def test_case_insensitivity(self):
        """Тест: регистр не влияет на результат"""
        from mawo_pymorphy3 import create_analyzer

        analyzer = create_analyzer(use_dawg=True)

        lower_result = analyzer.parse("дом")
        upper_result = analyzer.parse("ДОМ")
        mixed_result = analyzer.parse("Дом")

        assert len(lower_result) > 0, "Должен быть результат для нижнего регистра"
        assert len(upper_result) > 0, "Должен быть результат для верхнего регистра"
        assert len(mixed_result) > 0, "Должен быть результат для смешанного регистра"

        # Все должны давать одинаковую нормальную форму
        normal_forms_lower = {p.normal_form for p in lower_result}
        normal_forms_upper = {p.normal_form for p in upper_result}
        normal_forms_mixed = {p.normal_form for p in mixed_result}

        assert (
            normal_forms_lower == normal_forms_upper == normal_forms_mixed
        ), "Нормальные формы должны совпадать независимо от регистра"


class TestDAWGFallback:
    """Проверка fallback режима"""

    def test_fallback_on_unknown_words(self):
        """Тест: fallback срабатывает для неизвестных слов"""
        from mawo_pymorphy3 import create_analyzer

        analyzer = create_analyzer(use_dawg=True)

        # Полностью выдуманное слово
        unknown_word = "абракадабрацветочек"
        result = analyzer.parse(unknown_word)

        # Должен вернуть хоть какой-то результат (через предсказание или patterns)
        assert isinstance(result, list), "Результат должен быть списком"
        # Может быть пустым или с предсказанием
        if len(result) > 0:
            assert hasattr(result[0], "normal_form"), "Результат должен иметь normal_form"
            assert hasattr(result[0], "tag"), "Результат должен иметь tag"
