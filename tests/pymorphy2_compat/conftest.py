import pytest


@pytest.fixture(scope="session")
def morph():
    """Создает анализатор из mawo_pymorphy3 для совместимости с pymorphy2 тестами"""
    import os

    # Используем DAWG словари для быстрого тестирования
    os.environ["MAWO_FAST_MODE"] = "0"

    from mawo_pymorphy3 import MorphAnalyzer

    return MorphAnalyzer()


@pytest.fixture(scope="session")
def Tag(morph):  # noqa: N802
    """Возвращает класс Tag для тестов"""
    # В pymorphy2 это morph.TagClass, у нас это MAWOTag
    from mawo_pymorphy3 import MAWOTag

    return MAWOTag
