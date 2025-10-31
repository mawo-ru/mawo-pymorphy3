"""
Комплексные тесты для mawo-pymorphy3
Проверяют всю функциональность описанную в README
"""

from pathlib import Path

import pytest


class TestREADMEExamples:
    """Тесты примеров из README"""

    def test_quick_start_example(self):
        """Тест: быстрый старт из README работает"""
        from mawo_pymorphy3 import create_analyzer

        # Создаём анализатор (автоматически загружает DAWG словарь)
        analyzer = create_analyzer()
        assert analyzer is not None

        # Разбираем русские слова
        word = analyzer.parse("дом")[0]
        assert word.tag is not None
        assert word.normal_form is not None
        assert hasattr(word, 'word')

    def test_global_analyzer(self):
        """Тест: get_global_analyzer() работает"""
        from mawo_pymorphy3 import get_global_analyzer

        analyzer = get_global_analyzer()
        assert analyzer is not None

        # Должен вернуть тот же экземпляр при повторном вызове
        analyzer2 = get_global_analyzer()
        assert analyzer is analyzer2

    def test_inflect_method(self):
        """Тест: метод inflect() работает"""
        from mawo_pymorphy3 import create_analyzer

        analyzer = create_analyzer()
        word = analyzer.parse("дом")[0]

        # Должен иметь метод inflect
        assert hasattr(word, 'inflect')
        assert callable(word.inflect)

    def test_dictionary_manager(self):
        """Тест: MAWODictionaryManager работает"""
        from mawo_pymorphy3 import MAWODictionaryManager

        manager = MAWODictionaryManager()
        assert manager is not None

        # Проверяем методы
        assert hasattr(manager, 'is_dawg_cache_available')
        assert hasattr(manager, 'build_dawg_cache')
        assert hasattr(manager, 'get_cache_info')

        # Проверяем is_dawg_cache_available
        result = manager.is_dawg_cache_available()
        assert isinstance(result, bool)

        # Проверяем get_cache_info
        info = manager.get_cache_info()
        assert isinstance(info, dict)
        assert 'dict_path' in info
        assert 'dawg_available' in info


class TestCoreFunctionality:
    """Тесты базовой функциональности"""

    def test_create_analyzer(self):
        """Тест: create_analyzer создает анализатор"""
        from mawo_pymorphy3 import create_analyzer

        analyzer = create_analyzer()
        assert analyzer is not None
        assert hasattr(analyzer, 'parse')
        assert hasattr(analyzer, 'dictionary')

    def test_parse_returns_list(self):
        """Тест: parse возвращает список"""
        from mawo_pymorphy3 import create_analyzer

        analyzer = create_analyzer()
        result = analyzer.parse("тест")

        assert isinstance(result, list)
        assert len(result) > 0

    def test_parse_result_structure(self):
        """Тест: результат parse имеет правильную структуру"""
        from mawo_pymorphy3 import create_analyzer

        analyzer = create_analyzer()
        result = analyzer.parse("дом")

        assert len(result) > 0
        parse = result[0]

        # Проверяем обязательные атрибуты
        assert hasattr(parse, 'word')
        assert hasattr(parse, 'normal_form')
        assert hasattr(parse, 'tag')
        assert hasattr(parse, 'score')

    def test_tag_properties(self):
        """Тест: тег имеет все свойства"""
        from mawo_pymorphy3 import create_analyzer

        analyzer = create_analyzer()
        result = analyzer.parse("дом")
        tag = result[0].tag

        # Проверяем обязательные свойства
        assert hasattr(tag, 'POS')
        assert hasattr(tag, 'grammemes')
        assert hasattr(tag, 'case')
        assert hasattr(tag, 'number')
        assert hasattr(tag, 'gender')

    def test_empty_string(self):
        """Тест: пустая строка возвращает пустой список"""
        from mawo_pymorphy3 import create_analyzer

        analyzer = create_analyzer()
        result = analyzer.parse("")

        assert isinstance(result, list)
        assert len(result) == 0

    def test_whitespace_only(self):
        """Тест: только пробелы возвращают пустой список"""
        from mawo_pymorphy3 import create_analyzer

        analyzer = create_analyzer()
        result = analyzer.parse("   ")

        assert isinstance(result, list)
        assert len(result) == 0


class TestInflection:
    """Тесты изменения словоформ"""

    def test_inflect_exists(self):
        """Тест: метод inflect существует"""
        from mawo_pymorphy3 import create_analyzer

        analyzer = create_analyzer()
        word = analyzer.parse("дом")[0]

        assert hasattr(word, 'inflect')

    def test_inflect_returns_parse_or_none(self):
        """Тест: inflect возвращает MAWOParse или None"""
        from mawo_pymorphy3 import MAWOParse, create_analyzer

        analyzer = create_analyzer()
        word = analyzer.parse("дом")[0]

        result = word.inflect({"sing"})
        assert result is None or isinstance(result, MAWOParse)


class TestThreadSafety:
    """Тесты потокобезопасности"""

    def test_multiple_analyzers_singleton(self):
        """Тест: множественные вызовы create_analyzer возвращают один экземпляр"""
        from mawo_pymorphy3 import create_analyzer

        analyzer1 = create_analyzer()
        analyzer2 = create_analyzer()

        # Должны быть одним экземпляром (синглтон)
        assert analyzer1 is analyzer2

    def test_concurrent_parse(self):
        """Тест: параллельный parse работает корректно"""
        import threading

        from mawo_pymorphy3 import create_analyzer

        analyzer = create_analyzer()
        results = []
        errors = []

        def parse_word(word):
            try:
                result = analyzer.parse(word)
                results.append(result)
            except Exception as e:
                errors.append(e)

        threads = [
            threading.Thread(target=parse_word, args=("дом",)),
            threading.Thread(target=parse_word, args=("кот",)),
            threading.Thread(target=parse_word, args=("мир",)),
        ]

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0
        assert len(results) == 3


class TestCompability:
    """Тесты совместимости с pymorphy3"""

    def test_morphanalyzer_alias(self):
        """Тест: MorphAnalyzer это алиас для MAWOMorphAnalyzer"""
        from mawo_pymorphy3 import MAWOMorphAnalyzer, MorphAnalyzer

        assert MorphAnalyzer is MAWOMorphAnalyzer

    def test_all_exports(self):
        """Тест: все необходимые объекты экспортированы"""
        import mawo_pymorphy3

        # Проверяем наличие всех основных экспортов
        assert hasattr(mawo_pymorphy3, 'MAWOMorphAnalyzer')
        assert hasattr(mawo_pymorphy3, 'MAWOParse')
        assert hasattr(mawo_pymorphy3, 'MAWOTag')
        assert hasattr(mawo_pymorphy3, 'MorphAnalyzer')
        assert hasattr(mawo_pymorphy3, 'create_analyzer')
        assert hasattr(mawo_pymorphy3, 'get_global_analyzer')
        assert hasattr(mawo_pymorphy3, 'MAWODictionaryManager')


class TestDataFiles:
    """Тесты наличия файлов данных"""

    def test_dicts_directory_exists(self):
        """Тест: директория dicts_ru существует"""
        from mawo_pymorphy3 import create_analyzer

        analyzer = create_analyzer()
        data_path = Path(analyzer.dict_path)

        # Ищем директорию dicts_ru
        dicts_ru_path = data_path.parent / "dicts_ru"
        if not dicts_ru_path.exists():
            # Возможно data_path уже указывает на dicts_ru
            if data_path.name == "dicts_ru":
                dicts_ru_path = data_path

        assert dicts_ru_path.exists(), f"Directory {dicts_ru_path} does not exist"

    def test_dawg_files_present(self):
        """Тест: DAWG файлы присутствуют"""
        import mawo_pymorphy3

        package_dir = Path(mawo_pymorphy3.__file__).parent
        dicts_ru = package_dir / "dicts_ru"

        assert dicts_ru.exists(), f"dicts_ru directory not found at {dicts_ru}"

        # Проверяем наличие хотя бы одного DAWG файла
        dawg_files = list(dicts_ru.glob("*.dawg"))
        assert len(dawg_files) > 0, "No DAWG files found in dicts_ru"


class TestRussianMorphology:
    """Тесты русской морфологии"""

    def test_noun_recognition(self):
        """Тест: распознавание существительных"""
        from mawo_pymorphy3 import create_analyzer

        analyzer = create_analyzer()
        result = analyzer.parse("дом")

        assert len(result) > 0
        # Проверяем что есть вариант с NOUN
        tags = [str(p.tag) for p in result]
        has_noun = any('NOUN' in tag for tag in tags)
        assert has_noun, f"Expected NOUN in tags, got: {tags}"

    def test_verb_recognition(self):
        """Тест: распознавание глаголов"""
        from mawo_pymorphy3 import create_analyzer

        analyzer = create_analyzer()
        result = analyzer.parse("бежать")

        assert len(result) > 0
        tags = [str(p.tag) for p in result]
        has_verb = any('VERB' in tag or 'INFN' in tag for tag in tags)
        assert has_verb, f"Expected VERB/INFN in tags, got: {tags}"

    def test_case_detection(self):
        """Тест: определение падежа"""
        from mawo_pymorphy3 import create_analyzer

        analyzer = create_analyzer()
        result = analyzer.parse("дома")  # родительный падеж

        assert len(result) > 0
        # Проверяем что хотя бы один вариант имеет падеж
        has_case = any(p.tag.case is not None for p in result)
        assert has_case, "Expected case to be detected"


if __name__ == '__main__':
    pytest.main([__file__, '-v', '--tb=short'])
