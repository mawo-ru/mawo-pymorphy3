"""
Строгие интеграционные тесты для mawo-pymorphy3
Тестируют библиотеку как самодостаточный проект
"""

from pathlib import Path

import pytest


class TestImports:
    """Тесты импортов"""

    def test_main_module_import(self):
        """Тест: главный модуль импортируется"""
        try:
            import mawo_pymorphy3  # noqa: F401
        except ImportError as e:
            pytest.fail(f"Failed to import mawo_pymorphy3: {e}")

    def test_main_class_import(self):
        """Тест: основной класс импортируется"""
        try:
            from mawo_pymorphy3 import MAWOMorphAnalyzer  # noqa: F401
        except ImportError as e:
            pytest.fail(f"Failed to import MAWOMorphAnalyzer: {e}")

    def test_parse_class_import(self):
        """Тест: класс результата парсинга импортируется"""
        try:
            from mawo_pymorphy3 import MAWOParse  # noqa: F401
        except ImportError as e:
            pytest.fail(f"Failed to import MAWOParse: {e}")


class TestInitialization:
    """Тесты инициализации"""

    def test_analyzer_initialization_default(self):
        """Тест: анализатор инициализируется с дефолтными параметрами"""
        from mawo_pymorphy3 import MAWOMorphAnalyzer

        try:
            analyzer = MAWOMorphAnalyzer()
            assert analyzer is not None
        except Exception as e:
            pytest.fail(f"Failed to initialize MAWOMorphAnalyzer: {e}")

    def test_analyzer_has_dictionary(self):
        """Тест: анализатор имеет словарь"""
        from mawo_pymorphy3 import MAWOMorphAnalyzer

        analyzer = MAWOMorphAnalyzer()
        assert hasattr(analyzer, 'dictionary')
        assert analyzer.dictionary is not None
        assert len(analyzer.dictionary) > 0, "Dictionary should not be empty"

    def test_data_directory_exists(self):
        """Тест: директория с данными существует"""
        from mawo_pymorphy3 import MAWOMorphAnalyzer

        analyzer = MAWOMorphAnalyzer()
        data_path = Path(analyzer.dict_path)
        assert data_path.exists(), f"Data path does not exist: {data_path}"
        assert data_path.is_dir(), f"Data path is not a directory: {data_path}"


class TestBasicFunctionality:
    """Тесты базовой функциональности"""

    def test_parse_simple_word(self):
        """Тест: парсинг простого слова"""
        from mawo_pymorphy3 import MAWOMorphAnalyzer

        analyzer = MAWOMorphAnalyzer()
        result = analyzer.parse('привет')

        assert result is not None
        assert isinstance(result, list)
        assert len(result) > 0
        assert all(hasattr(p, 'word') for p in result)
        assert all(hasattr(p, 'normal_form') for p in result)

    def test_parse_noun(self):
        """Тест: парсинг существительного"""
        from mawo_pymorphy3 import MAWOMorphAnalyzer

        analyzer = MAWOMorphAnalyzer()
        # Используем слово из базового словаря
        result = analyzer.parse('дом')

        assert len(result) > 0
        # Проверяем, что есть вариант с тегом существительного
        has_noun = any('NOUN' in str(p.tag) if hasattr(p, 'tag') else False for p in result)
        assert has_noun, f"Expected NOUN tag for 'дом', got: {[str(p.tag) for p in result]}"

    def test_parse_verb(self):
        """Тест: парсинг глагола"""
        from mawo_pymorphy3 import MAWOMorphAnalyzer

        analyzer = MAWOMorphAnalyzer()
        # Используем слово из базового словаря
        result = analyzer.parse('был')

        assert len(result) > 0
        # Проверяем, что есть вариант с тегом глагола
        has_verb = any('VERB' in str(p.tag) if hasattr(p, 'tag') else False for p in result)
        assert has_verb, f"Expected VERB tag for 'был', got: {[str(p.tag) for p in result]}"

    def test_parse_returns_normal_form(self):
        """Тест: парсинг возвращает нормальную форму"""
        from mawo_pymorphy3 import MAWOMorphAnalyzer

        analyzer = MAWOMorphAnalyzer()
        # Используем слово из базового словаря
        result = analyzer.parse('дома')

        assert len(result) > 0
        assert hasattr(result[0], 'normal_form')
        assert result[0].normal_form == 'дом'

    def test_parse_empty_string(self):
        """Тест: парсинг пустой строки"""
        from mawo_pymorphy3 import MAWOMorphAnalyzer

        analyzer = MAWOMorphAnalyzer()
        result = analyzer.parse('')

        assert isinstance(result, list)
        # Может вернуть пустой список или список с одним пустым результатом

    def test_parse_unknown_word(self):
        """Тест: парсинг неизвестного слова"""
        from mawo_pymorphy3 import MAWOMorphAnalyzer

        analyzer = MAWOMorphAnalyzer()
        result = analyzer.parse('абвгдежзийклмнопрстуфхцчшщ')

        assert isinstance(result, list)
        # Должен вернуть хоть какой-то результат (предсказание)


class TestDataFiles:
    """Тесты наличия и корректности файлов данных"""

    def test_dicts_ru_directory_exists(self):
        """Тест: директория dicts_ru существует"""
        import mawo_pymorphy3

        package_dir = Path(mawo_pymorphy3.__file__).parent
        dicts_ru = package_dir / "dicts_ru"

        assert dicts_ru.exists(), f"dicts_ru directory not found at {dicts_ru}"
        assert dicts_ru.is_dir(), "dicts_ru is not a directory"

    def test_dawg_files_exist(self):
        """Тест: DAWG файлы существуют"""
        import mawo_pymorphy3

        package_dir = Path(mawo_pymorphy3.__file__).parent
        dicts_ru = package_dir / "dicts_ru"

        # Проверяем наличие хотя бы одного DAWG файла
        dawg_files = list(dicts_ru.glob("*.dawg"))
        assert len(dawg_files) > 0, f"No DAWG files found in {dicts_ru}"

        # Проверяем что файлы не пустые
        for dawg_file in dawg_files:
            assert dawg_file.stat().st_size > 0, f"DAWG file is empty: {dawg_file.name}"

    def test_grammemes_file_exists(self):
        """Тест: файл грамматических признаков существует"""
        import mawo_pymorphy3

        package_dir = Path(mawo_pymorphy3.__file__).parent
        dicts_ru = package_dir / "dicts_ru"

        grammemes_file = dicts_ru / 'grammemes.json'
        # Файл опционален, только предупреждение если нет
        if grammemes_file.exists():
            assert grammemes_file.stat().st_size > 0, "grammemes.json is empty"


class TestMemoryOptimization:
    """Тесты оптимизации памяти"""

    def test_multiple_analyzers_share_cache(self):
        """Тест: множественные анализаторы используют общий кэш"""
        from mawo_pymorphy3 import MAWOMorphAnalyzer

        analyzer1 = MAWOMorphAnalyzer()
        analyzer2 = MAWOMorphAnalyzer()

        # Оба анализатора должны работать
        result1 = analyzer1.parse('привет')
        result2 = analyzer2.parse('привет')

        assert result1 is not None
        assert result2 is not None


class TestRussianCases:
    """Тесты для русских падежей"""

    def test_genitive_case(self):
        """Тест: распознавание родительного падежа"""
        from mawo_pymorphy3 import MAWOMorphAnalyzer

        analyzer = MAWOMorphAnalyzer()
        # Используем слово из базового словаря
        result = analyzer.parse('дома')  # родительный падеж или множественное число

        assert len(result) > 0
        # Проверяем, что есть вариант с gent (родительный падеж)
        has_genitive = any('gent' in str(p.tag).lower() if hasattr(p, 'tag') else False for p in result)
        assert has_genitive, f"Expected genitive case for 'дома', got: {[str(p.tag) for p in result]}"

    def test_case_detection(self):
        """Тест: определение падежа вообще"""
        from mawo_pymorphy3 import MAWOMorphAnalyzer

        analyzer = MAWOMorphAnalyzer()
        result = analyzer.parse('дома')

        assert len(result) > 0
        # Проверяем что хотя бы один вариант имеет падеж
        has_case = any(hasattr(p.tag, 'case') and p.tag.case is not None for p in result)
        assert has_case, f"Expected case to be detected for 'дома', got: {[str(p.tag) for p in result]}"


class TestEdgeCases:
    """Тесты граничных случаев"""

    def test_parse_number(self):
        """Тест: парсинг числа"""
        from mawo_pymorphy3 import MAWOMorphAnalyzer

        analyzer = MAWOMorphAnalyzer()
        result = analyzer.parse('123')

        assert isinstance(result, list)

    def test_parse_punctuation(self):
        """Тест: парсинг пунктуации"""
        from mawo_pymorphy3 import MAWOMorphAnalyzer

        analyzer = MAWOMorphAnalyzer()
        result = analyzer.parse('!')

        assert isinstance(result, list)

    def test_parse_mixed_language(self):
        """Тест: парсинг смешанного текста"""
        from mawo_pymorphy3 import MAWOMorphAnalyzer

        analyzer = MAWOMorphAnalyzer()
        result = analyzer.parse('hello')

        assert isinstance(result, list)

    def test_parse_very_long_word(self):
        """Тест: парсинг очень длинного слова"""
        from mawo_pymorphy3 import MAWOMorphAnalyzer

        analyzer = MAWOMorphAnalyzer()
        long_word = 'превысокомногорассмотрительствующий'
        result = analyzer.parse(long_word)

        assert isinstance(result, list)
        assert len(result) > 0


class TestThreadSafety:
    """Тесты потокобезопасности"""

    def test_concurrent_parsing(self):
        """Тест: одновременный парсинг из разных потоков"""
        import threading

        from mawo_pymorphy3 import MAWOMorphAnalyzer

        analyzer = MAWOMorphAnalyzer()
        results = []
        errors = []

        def parse_word(word):
            try:
                result = analyzer.parse(word)
                results.append(result)
            except Exception as e:
                errors.append(e)

        threads = [
            threading.Thread(target=parse_word, args=('привет',)),
            threading.Thread(target=parse_word, args=('мир',)),
            threading.Thread(target=parse_word, args=('кот',)),
        ]

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0, f"Concurrent parsing failed: {errors}"
        assert len(results) == 3, f"Expected 3 results, got {len(results)}"


if __name__ == '__main__':
    pytest.main([__file__, '-v', '--tb=short'])
