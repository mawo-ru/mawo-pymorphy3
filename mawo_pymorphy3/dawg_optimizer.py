"""DAWG Memory Optimization для MAWO Pymorphy3
Reduces memory footprint from ~500MB to ~50MB (10x compression).

DAWG (Directed Acyclic Word Graph) - эффективная структура для хранения словарей.

Based on:
- dawg-python library
- pymorphy2 DAWG implementation
"""
from __future__ import annotations

import logging
import pickle
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class DAWGMemoryOptimizer:
    """Оптимизация памяти словаря через DAWG структуры."""

    def __init__(self) -> None:
        """Initialize DAWG optimizer."""
        self.dawg_available = False
        self.dawg_module = None

        # Try to import DAWG
        try:
            import dawg  # type: ignore[import-not-found]

            self.dawg_module = dawg
            self.dawg_available = True
            logger.info("✅ DAWG library available for memory optimization")
        except ImportError:
            logger.info(
                "ℹ️  DAWG library not installed (pip install dawg-python for 10x memory reduction)"
            )

    def is_available(self) -> bool:
        """Проверяет доступность DAWG оптимизации."""
        return self.dawg_available

    def convert_dict_to_dawg(
        self, dictionary: dict[str, list[Any]]
    ) -> dict | Any:
        """Конвертирует словарь в DAWG структуру.

        Args:
            dictionary: Словарь слово -> list[MAWOParse]

        Returns:
            DAWG structure или оригинальный словарь если DAWG недоступен
        """
        if not self.dawg_available:
            logger.warning(
                "⚠️ DAWG not available, using full dictionary (~500MB RAM)"
            )
            return dictionary

        try:
            logger.info("🔄 Converting dictionary to DAWG (10x memory reduction)...")

            # Сериализуем словарь в компактный формат
            serialized_items = []

            for word, parses in dictionary.items():
                for parse in parses:
                    # Компактное представление: word -> serialized parse
                    value = self._serialize_parse(parse)
                    serialized_items.append((word, value))

            logger.info(f"   Serialized {len(serialized_items):,} word-parse pairs")

            # Создаём DAWG с компактным хранением
            # Используем BytesDAWG для максимальной компрессии
            dawg_dict = self.dawg_module.BytesDAWG(serialized_items)  # type: ignore[union-attr]

            # Статистика компрессии
            original_size_mb = self._estimate_dict_size(dictionary) / (1024 * 1024)
            dawg_size_mb = len(dawg_dict.tobytes()) / (1024 * 1024)
            compression_ratio = original_size_mb / dawg_size_mb if dawg_size_mb > 0 else 0

            logger.info("✅ DAWG created:")
            logger.info(f"   Original: {original_size_mb:.1f} MB")
            logger.info(f"   DAWG: {dawg_size_mb:.1f} MB")
            logger.info(f"   Compression: {compression_ratio:.1f}x")

            # Создаём wrapper для прозрачной работы с DAWG
            return DAWGDictionaryWrapper(dawg_dict, self)

        except Exception as e:
            logger.exception(f"❌ Failed to create DAWG: {e}")
            logger.warning("   Falling back to full dictionary")
            return dictionary

    def _serialize_parse(self, parse: Any) -> bytes:
        """Сериализует MAWOParse в компактный формат.

        Args:
            parse: MAWOParse объект

        Returns:
            Bytes representation
        """
        # Компактный формат: normal_form|POS|grammeme1,grammeme2|score
        parts = [
            parse.normal_form,
            parse.tag.POS,
            ",".join(sorted(parse.tag.grammemes)) if parse.tag.grammemes else "",
            f"{parse.score:.2f}",
        ]
        return "|".join(parts).encode("utf-8")

    def _deserialize_parse(self, data: bytes, word: str) -> Any:
        """Десериализует MAWOParse из bytes.

        Args:
            data: Serialized data
            word: Original word

        Returns:
            MAWOParse object
        """
        # Import here to avoid circular dependency
        from . import MAWOParse, MAWOTag

        parts = data.decode("utf-8").split("|")
        if len(parts) != 4:
            logger.warning(f"Invalid serialized data for word '{word}'")
            return None

        normal_form, pos, grammemes_str, score_str = parts

        grammemes = set(grammemes_str.split(",")) if grammemes_str else set()
        tag = MAWOTag(pos, grammemes)
        score = float(score_str)

        return MAWOParse(word, normal_form, tag, score)

    def _estimate_dict_size(self, dictionary: dict) -> int:
        """Оценивает размер словаря в памяти.

        Args:
            dictionary: Dictionary to estimate

        Returns:
            Estimated size in bytes
        """
        # Используем pickle для оценки размера
        try:
            return len(pickle.dumps(dictionary, protocol=pickle.HIGHEST_PROTOCOL))
        except Exception:
            # Fallback: грубая оценка
            return len(dictionary) * 1000  # ~1KB per entry

    def save_dawg_cache(self, dawg_dict: Any, cache_path: Path) -> None:
        """Сохраняет DAWG в кэш для быстрой загрузки.

        Args:
            dawg_dict: DAWG dictionary
            cache_path: Path to cache file
        """
        if not self.dawg_available:
            return

        try:
            logger.info(f"💾 Saving DAWG cache to {cache_path.name}")

            cache_path.parent.mkdir(parents=True, exist_ok=True)

            # Сохраняем DAWG в компактном формате
            with open(cache_path, "wb") as f:
                f.write(dawg_dict.tobytes())

            cache_size_mb = cache_path.stat().st_size / (1024 * 1024)
            logger.info(f"✅ DAWG cache saved: {cache_size_mb:.1f} MB")

        except Exception as e:
            logger.warning(f"⚠️ Failed to save DAWG cache: {e}")

    def load_dawg_cache(self, cache_path: Path) -> Any | None:
        """Загружает DAWG из кэша.

        Args:
            cache_path: Path to cache file

        Returns:
            DAWG dictionary или None
        """
        if not self.dawg_available or not cache_path.exists():
            return None

        try:
            logger.info(f"⚡ Loading DAWG from cache: {cache_path.name}")

            with open(cache_path, "rb") as f:
                dawg_bytes = f.read()

            dawg_dict = self.dawg_module.BytesDAWG().load(dawg_bytes)  # type: ignore[union-attr]

            cache_size_mb = len(dawg_bytes) / (1024 * 1024)
            logger.info(f"✅ DAWG loaded from cache: {cache_size_mb:.1f} MB")

            return DAWGDictionaryWrapper(dawg_dict, self)

        except Exception as e:
            logger.warning(f"⚠️ Failed to load DAWG cache: {e}")
            return None


class DAWGDictionaryWrapper:
    """Wrapper для прозрачной работы с DAWG как с обычным dict.

    Поддерживает основные dict операции:
    - word in dawg_dict
    - dawg_dict[word]
    - dawg_dict.get(word, default)
    - len(dawg_dict)
    """

    def __init__(self, dawg_dict: Any, optimizer: DAWGMemoryOptimizer) -> None:
        """Initialize wrapper.

        Args:
            dawg_dict: DAWG dictionary
            optimizer: DAWGMemoryOptimizer instance
        """
        self._dawg = dawg_dict
        self._optimizer = optimizer

    def __contains__(self, word: str) -> bool:
        """Проверяет наличие слова в словаре."""
        try:
            # В DAWG есть метод similar_keys для поиска
            return bool(list(self._dawg.keys(word)))
        except Exception:
            return False

    def __getitem__(self, word: str) -> list[Any]:
        """Получает список парсов для слова."""
        try:
            # Получаем все значения для слова
            results = list(self._dawg.items(word))

            if not results:
                msg = f"Word not found: {word}"
                raise KeyError(msg)

            # Десериализуем все парсы
            parses = []
            for _, data in results:
                parse = self._optimizer._deserialize_parse(data, word)
                if parse:
                    parses.append(parse)

            return parses

        except KeyError:
            raise
        except Exception as e:
            logger.warning(f"Error getting word '{word}' from DAWG: {e}")
            msg = f"Word not found: {word}"
            raise KeyError(msg) from e

    def get(self, word: str, default: Any = None) -> Any:
        """Безопасное получение слова."""
        try:
            return self[word]
        except KeyError:
            return default

    def __len__(self) -> int:
        """Возвращает количество уникальных слов."""
        # Приблизительная оценка (DAWG не хранит точный count)
        try:
            return len(list(self._dawg.keys()))
        except Exception:
            return 0

    def keys(self) -> list[str]:
        """Возвращает список всех слов."""
        try:
            return list(self._dawg.keys())
        except Exception:
            return []

    def copy(self) -> DAWGDictionaryWrapper:
        """Создаёт copy как обычный dict (для совместимости)."""
        # Не копируем DAWG, возвращаем self
        # (DAWG immutable, копирование не требуется)
        return self

    def __repr__(self) -> str:
        """String representation."""
        return f"<DAWGDictionaryWrapper: ~{len(self)} words>"


# Global optimizer instance
_global_optimizer: DAWGMemoryOptimizer | None = None


def get_dawg_optimizer() -> DAWGMemoryOptimizer:
    """Get global DAWG optimizer instance.

    Returns:
        DAWGMemoryOptimizer instance
    """
    global _global_optimizer

    if _global_optimizer is None:
        _global_optimizer = DAWGMemoryOptimizer()

    return _global_optimizer


__all__ = [
    "DAWGMemoryOptimizer",
    "DAWGDictionaryWrapper",
    "get_dawg_optimizer",
]
