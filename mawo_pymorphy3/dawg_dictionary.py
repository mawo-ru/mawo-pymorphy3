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
        self.paradigms: list[Any] = []
        self.paradigm_prefixes: list[str] = []
        self.words_dawg: Any = None
        self.prediction_dawgs: list[Any] = []

        # Проверяем доступность библиотеки DAWG
        try:
            import dawg_python as dawg  # type: ignore[import-not-found]

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
        self._load_paradigm_prefixes()
        self._load_paradigms()
        self._load_words_dawg()
        self._load_prediction_dawgs()

        logger.info(f"✅ DAWG словарь загружен из {self.dict_path}")
        # Не вызываем keys() на DAWG - это очень медленно!
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

    def _load_paradigm_prefixes(self) -> None:
        """Загрузка префиксов парадигм из meta.json."""
        # Префиксы хранятся в compile_options.paradigm_prefixes
        self.paradigm_prefixes = self.meta.get("compile_options", {}).get("paradigm_prefixes", [""])

        logger.debug(f"🔤 Загружено {len(self.paradigm_prefixes)} префиксов парадигм")

    def _load_paradigms(self) -> None:
        """Загрузка парадигм из бинарного файла paradigms.array."""
        import array

        paradigms_path = self.dict_path / "paradigms.array"

        with open(paradigms_path, "rb") as f:
            paradigms_count = struct.unpack("<H", f.read(2))[0]

            self.paradigms = []
            for _ in range(paradigms_count):
                paradigm_len = struct.unpack("<H", f.read(2))[0]
                para = array.array("H")
                para.fromfile(f, paradigm_len)
                self.paradigms.append(para)

        logger.debug(f"📦 Загружено {len(self.paradigms)} парадигм")

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

    def get_paradigm(self, paradigm_id: int, word_idx: int) -> tuple[str, str, str] | None:
        """Получить информацию о парадигме.

        Args:
            paradigm_id: ID парадигмы
            word_idx: Индекс словоформы в парадигме

        Returns:
            Кортеж (suffix, tag_string, prefix) или None
            tag_string - строка вида "NOUN,anim,masc sing,nomn"
        """
        if paradigm_id >= len(self.paradigms):
            return None

        paradigm = self.paradigms[paradigm_id]
        paradigm_len = len(paradigm) // 3

        if word_idx >= paradigm_len:
            return None

        # Извлекаем suffix_id, tag_id, prefix_id
        suffix_id = paradigm[word_idx]
        tag_id = paradigm[paradigm_len + word_idx]
        prefix_id = paradigm[paradigm_len * 2 + word_idx]

        if suffix_id >= len(self.suffixes):
            return None

        suffix = self.suffixes[suffix_id]

        if tag_id >= len(self.gramtab):
            return None

        tag_string = self.gramtab[tag_id]

        if prefix_id >= len(self.paradigm_prefixes):
            return None

        prefix = self.paradigm_prefixes[prefix_id]

        return (suffix, tag_string, prefix)

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

    def get_all_paradigm_forms(self, paradigm_id: int) -> list[tuple[str, str, str]]:
        """Получить все формы парадигмы (лексему).

        Args:
            paradigm_id: ID парадигмы

        Returns:
            Список кортежей (suffix, tag_string, prefix) для всех форм
        """
        if paradigm_id >= len(self.paradigms):
            return []

        paradigm = self.paradigms[paradigm_id]
        paradigm_len = len(paradigm) // 3

        forms = []
        for word_idx in range(paradigm_len):
            form_info = self.get_paradigm(paradigm_id, word_idx)
            if form_info:
                forms.append(form_info)

        return forms


__all__ = ["DAWGDictionary"]
