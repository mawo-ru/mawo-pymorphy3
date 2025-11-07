"""Загрузчик DAWG словарей в формате pymorphy2
Загружает скомпилированные словари в формате pymorphy2 с DAWG структурами.
"""

from __future__ import annotations

import json
import logging
import struct
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class DAWGDictionary:
    """Загружает и предоставляет доступ к DAWG словарям pymorphy2."""

    def __init__(self, dict_path: str | Path) -> None:
        """Инициализация загрузчика DAWG словаря.

        Args:
            dict_path: Путь к директории со словарными файлами pymorphy2
        """
        self.dict_path = Path(dict_path)
        self.meta: dict[str, Any] = {}
        self.grammemes: list[list[str]] = []
        self.suffixes: list[str] = []
        self.gramtab: list[list[int]] = []
        self.paradigms: list[tuple[int, int]] = []
        self.words_dawg: Any = None
        self.prediction_dawgs: list[Any] = []

        # Проверяем доступность библиотеки DAWG
        try:
            import dawg  # type: ignore[import-not-found]

            self._dawg_module = dawg
            self._dawg_available = True
        except ImportError:
            logger.error("❌ dawg-python не установлен. Установите: pip install dawg-python")
            self._dawg_available = False
            raise ImportError("dawg-python требуется для поддержки DAWG словарей") from None

        # Загружаем все компоненты словаря
        self._load_meta()
        self._load_grammemes()
        self._load_suffixes()
        self._load_gramtab()
        self._load_paradigms()
        self._load_words_dawg()
        self._load_prediction_dawgs()

        logger.info(f"✅ DAWG словарь загружен из {self.dict_path}")
        logger.info(f"   Слов: {len(list(self.words_dawg.keys()))} записей")
        logger.info(f"   Парадигм: {len(self.paradigms)}")
        logger.info(f"   Суффиксов: {len(self.suffixes)}")
        logger.info(f"   Граммем: {len(self.gramtab)} тегов")

    def _load_meta(self) -> None:
        """Загрузка метаданных словаря из meta.json."""
        meta_path = self.dict_path / "meta.json"
        with open(meta_path, encoding="utf-8") as f:
            meta_list = json.load(f)
            self.meta = dict(meta_list)

        logger.info(f"📋 Загружены метаданные: формат {self.meta.get('format_version')}")

    def _load_grammemes(self) -> None:
        """Загрузка граммем из grammemes.json."""
        grammemes_path = self.dict_path / "grammemes.json"
        with open(grammemes_path, encoding="utf-8") as f:
            self.grammemes = json.load(f)

        logger.debug(f"📚 Загружено {len(self.grammemes)} граммем")

    def _load_suffixes(self) -> None:
        """Загрузка суффиксов из suffixes.json."""
        suffixes_path = self.dict_path / "suffixes.json"
        with open(suffixes_path, encoding="utf-8") as f:
            self.suffixes = json.load(f)

        logger.debug(f"📝 Загружено {len(self.suffixes)} суффиксов")

    def _load_gramtab(self) -> None:
        """Загрузка грамматической таблицы из gramtab-opencorpora-int.json."""
        gramtab_format = self.meta.get("gramtab_formats", {}).get(
            "opencorpora-int", "gramtab-opencorpora-int.json"
        )
        gramtab_path = self.dict_path / gramtab_format

        with open(gramtab_path, encoding="utf-8") as f:
            self.gramtab = json.load(f)

        logger.debug(f"🏷️  Загружено {len(self.gramtab)} записей gramtab")

    def _load_paradigms(self) -> None:
        """Загрузка парадигм из бинарного файла paradigms.array."""
        paradigms_path = self.dict_path / "paradigms.array"

        with open(paradigms_path, "rb") as f:
            paradigms_data = f.read()

        # Каждая форма - 2 unsigned shorts (little-endian): (suffix_id, gramtab_id)
        paradigm_format = "<HH"  # little-endian!
        paradigm_size = struct.calcsize(paradigm_format)
        paradigms_count = len(paradigms_data) // paradigm_size

        self.paradigms = []
        for i in range(paradigms_count):
            offset = i * paradigm_size
            suffix_id, gramtab_id = struct.unpack(
                paradigm_format, paradigms_data[offset : offset + paradigm_size]
            )
            self.paradigms.append((suffix_id, gramtab_id))

        logger.debug(f"📦 Загружено {len(self.paradigms)} словоформ в парадигмах")

    def _load_words_dawg(self) -> None:
        """Загрузка слов из words.dawg."""
        words_path = self.dict_path / "words.dawg"

        # RecordDAWG с форматом >HH (paradigm_id, word_idx)
        self.words_dawg = self._dawg_module.RecordDAWG(">HH")
        self.words_dawg = self.words_dawg.load(str(words_path))

        logger.debug(f"📖 Загружен DAWG слов из {words_path.name}")

    def _load_prediction_dawgs(self) -> None:
        """Загрузка DAWG словарей для предсказания."""
        prefix_count = len(self.meta.get("compile_options", {}).get("paradigm_prefixes", [""]))

        self.prediction_dawgs = []
        for prefix_id in range(prefix_count):
            prediction_path = self.dict_path / f"prediction-suffixes-{prefix_id}.dawg"

            if prediction_path.exists():
                # PredictionSuffixesDAWG использует тот же формат
                pred_dawg = self._dawg_module.RecordDAWG(">HH")
                pred_dawg = pred_dawg.load(str(prediction_path))
                self.prediction_dawgs.append(pred_dawg)
            else:
                logger.warning(f"⚠️  Prediction DAWG не найден: {prediction_path.name}")

        logger.debug(f"🔮 Загружено {len(self.prediction_dawgs)} prediction DAWGs")

    def get_word_parses(self, word: str) -> list[tuple[int, int]]:
        """Получить разборы слова из DAWG.

        Args:
            word: Слово для поиска

        Returns:
            Список кортежей (paradigm_id, word_idx)
        """
        if word not in self.words_dawg:
            return []

        return self.words_dawg[word]

    def get_paradigm(self, paradigm_id: int, word_idx: int) -> tuple[str, str] | None:
        """Получить информацию о парадигме.

        Args:
            paradigm_id: ID парадигмы
            word_idx: Индекс словоформы в парадигме

        Returns:
            Кортеж (suffix, tag_string) или None
            tag_string - строка вида "NOUN,anim,masc sing,nomn"
        """
        # В pymorphy2 парадигмы хранятся последовательно в paradigms.array
        # paradigm_id + word_idx дает позицию конкретной словоформы
        form_index = paradigm_id + word_idx

        if form_index >= len(self.paradigms):
            return None

        suffix_id, gramtab_id = self.paradigms[form_index]

        if suffix_id >= len(self.suffixes):
            return None

        suffix = self.suffixes[suffix_id]

        if gramtab_id >= len(self.gramtab):
            return None

        tag_string = self.gramtab[gramtab_id]

        return (suffix, tag_string)

    def parse_tag_string(self, tag_string: str) -> tuple[str, set[str]]:
        """Разобрать строку тега на POS и граммемы.

        Args:
            tag_string: Строка вида "NOUN,anim,masc sing,nomn"

        Returns:
            Кортеж (POS, set(grammemes))
            Например: ("NOUN", {"anim", "masc", "sing", "nomn"})
        """
        parts = tag_string.replace(" ", ",").split(",")
        if not parts:
            return ("UNKN", set())

        pos = parts[0]
        grammemes = set(parts[1:]) if len(parts) > 1 else set()

        return (pos, grammemes)

    def word_is_known(self, word: str) -> bool:
        """Проверить наличие слова в словаре.

        Args:
            word: Слово для проверки

        Returns:
            True если слово известно
        """
        return word in self.words_dawg


__all__ = ["DAWGDictionary"]
