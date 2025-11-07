"""MAWO морфологический анализатор
Использует улучшенный словарь OpenCorpora и современные алгоритмы.
"""

from __future__ import annotations

import logging
import pickle
from pathlib import Path
from typing import Any

try:
    from defusedxml.ElementTree import parse as defusedxml_parse  # type: ignore[import-not-found]

    ET_PARSE_SAFE = True
except ImportError:
    ET_PARSE_SAFE = False

# Rich для прогресс бара и красивого вывода
try:
    from rich.console import Console
    from rich.panel import Panel

    RICH_AVAILABLE = True
except ImportError:
    RICH_AVAILABLE = False

# Исправляем getargspec проблему для Python 3.11+
import inspect

if not hasattr(inspect, "getargspec"):
    inspect.getargspec = inspect.getfullargspec  # type: ignore[assignment]

logger = logging.getLogger(__name__)

# Глобальный кэш для предотвращения множественной загрузки OpenCorpora словаря
_GLOBAL_DICTIONARY_CACHE = None
_GLOBAL_PATTERNS_CACHE = None

# Синглтон экземпляр анализатора для предотвращения множественной инициализации
_GLOBAL_ANALYZER_INSTANCE = None
_ANALYZER_LOCK = None

# Импорт threading если не доступен
try:
    import threading

    _ANALYZER_LOCK = threading.Lock()
except ImportError:
    _ANALYZER_LOCK = None


class MAWOTag:
    """Морфологический тег в формате MAWO."""

    def __init__(self, pos: str = "UNKN", grammemes: set[str] | None = None) -> None:
        self.POS = pos
        self.grammemes = grammemes or set()

    @property
    def case(self) -> str | None:
        cases = {"nomn", "gent", "datv", "accs", "ablt", "loct", "voct"}
        return next((g for g in self.grammemes if g in cases), None)

    @property
    def number(self) -> str | None:
        numbers = {"sing", "plur"}
        return next((g for g in self.grammemes if g in numbers), None)

    @property
    def gender(self) -> str | None:
        genders = {"masc", "femn", "neut"}
        return next((g for g in self.grammemes if g in genders), None)

    @property
    def aspect(self) -> str | None:
        aspects = {"perf", "impf"}
        return next((g for g in self.grammemes if g in aspects), None)

    @property
    def tense(self) -> str | None:
        tenses = {"past", "pres", "futr"}
        return next((g for g in self.grammemes if g in tenses), None)

    def __contains__(self, item: Any) -> bool:
        return item in self.grammemes or item == self.POS

    def __str__(self) -> str:
        if not self.grammemes:
            return str(self.POS)
        return f"{self.POS} {','.join(sorted(self.grammemes))}"


class MAWOParse:
    """Результат морфологического анализа."""

    def __init__(
        self,
        word: str,
        normal_form: str,
        tag: MAWOTag,
        score: float = 1.0,
        analyzer: Any | None = None,
    ) -> None:
        self.word = word
        self.normal_form = normal_form
        self.tag = tag
        self.score = score
        self._analyzer = analyzer

    def inflect(self, required_grammemes: set[str]) -> MAWOParse | None:
        """Получение словоформы с заданными грамматическими признаками.

        Args:
            required_grammemes: Множество требуемых граммем (например, {"sing", "femn"})

        Returns:
            MAWOParse с нужными граммемами или None если не найдено
        """
        if not self._analyzer or not hasattr(self._analyzer, "dictionary"):
            # Простая заглушка если анализатор недоступен
            logger.warning("Analyzer not available for inflection, returning None")
            return None

        # Ищем формы нормальной формы слова
        normal_parses = self._analyzer.dictionary.get(self.normal_form, [])

        # Ищем форму с нужными граммемами
        for parse_item in normal_parses:
            if required_grammemes.issubset(parse_item.tag.grammemes):
                return parse_item  # type: ignore[no-any-return]

        # Если точное совпадение не найдено, ищем частичное
        for parse_item in normal_parses:
            matching_grammemes = parse_item.tag.grammemes & required_grammemes
            if matching_grammemes:
                return parse_item  # type: ignore[no-any-return]

        return None

    def __repr__(self) -> str:
        return f"MAWOParse(word='{self.word}', normal_form='{self.normal_form}', tag='{self.tag}', score={self.score})"


class MAWOMorphAnalyzer:
    """Главный морфологический анализатор MAWO
    Полная замена pymorphy2 с улучшенным словарем OpenCorpora.
    """

    def __init__(self, dict_path: str | None = None, use_dawg: bool = True) -> None:
        global _GLOBAL_DICTIONARY_CACHE, _GLOBAL_PATTERNS_CACHE

        # По умолчанию используем встроенные DAWG словари из dicts_ru
        self.dict_path = dict_path or str(Path(__file__).parent / "dicts_ru")
        self.use_dawg = use_dawg
        self._pymorphy2_analyzer: Any = None

        # Используем pymorphy2 с DAWG если указано
        if self.use_dawg and Path(self.dict_path).exists():
            try:
                import pymorphy2

                logger.info("⚡ Загрузка DAWG словарей через pymorphy2...")
                self._pymorphy2_analyzer = pymorphy2.MorphAnalyzer(path=self.dict_path)
                self.dictionary: dict[str, list[MAWOParse]] = {}

                logger.info("✅ DAWG словари загружены успешно!")
                logger.info(f"   Путь к словарям: {self.dict_path}")
                logger.info("   Память: ~15-20 МБ (DAWG)")

                # Инициализируем patterns для fallback на неизвестные слова
                self.patterns: dict[str, Any] = {}
                self._init_patterns()

                # Для совместимости с тестами
                self._analyzer = self
                self._production_analyzer = None

                logger.info(
                    "✅ MAWO Morphological Analyzer initialized with DAWG dictionaries",
                )

                return  # Готово, не нужен fallback

            except ImportError:
                logger.warning("⚠️ pymorphy2 не установлен, используем fallback")
                self.use_dawg = False
            except Exception as e:
                logger.warning(f"⚠️ Ошибка загрузки DAWG: {e}, используем fallback")
                self.use_dawg = False

        # Fallback: загрузка через кэш или XML
        if _GLOBAL_DICTIONARY_CACHE is None:
            logger.info("🔄 Инициализация (fallback режим) - загрузка словаря...")

            # Показываем красивый заголовок ТОЛЬКО при реальной загрузке
            if RICH_AVAILABLE:
                console = Console()
                console.print(
                    Panel(
                        "[bold blue]📚 Инициализация морфологического анализатора MAWO[/bold blue]\n"
                        "[dim]Загрузка словаря OpenCorpora для русскоязычной оптимизации...[/dim]",
                        title="OpenCorpora",
                    ),
                )

            self.dictionary: dict[str, list[MAWOParse]] = {}
            self._load_dictionary()
            _GLOBAL_DICTIONARY_CACHE = self.dictionary.copy()
            logger.info(
                f"💾 OpenCorpora dictionary cached ({len(_GLOBAL_DICTIONARY_CACHE)} entries)",
            )
        else:
            logger.debug("⚡ Using cached OpenCorpora dictionary - no reload needed!")  # type: ignore[unreachable]
            self.dictionary = _GLOBAL_DICTIONARY_CACHE.copy()

        if _GLOBAL_PATTERNS_CACHE is None:
            self.patterns: dict[str, Any] = {}
            self._init_patterns()
            _GLOBAL_PATTERNS_CACHE = self.patterns.copy()
        else:
            self.patterns = _GLOBAL_PATTERNS_CACHE.copy()  # type: ignore[unreachable]

        # Для совместимости с тестами
        self._analyzer = self
        self._production_analyzer = None

        logger.info(
            f"✅ MAWO Morphological Analyzer initialized with {len(self.dictionary)} entries",
        )

    def _get_cache_path(self, xml_path: Path) -> Path:
        """Получение пути к pickle-кэшу словаря."""
        return xml_path.parent / f"{xml_path.stem}.pkl"

    def _is_cache_valid(self, xml_path: Path, cache_path: Path) -> bool:
        """Проверка актуальности кэша."""
        if not cache_path.exists():
            return False

        # Проверяем что кэш новее XML
        xml_mtime = xml_path.stat().st_mtime
        cache_mtime = cache_path.stat().st_mtime

        return bool(cache_mtime >= xml_mtime)

    def _load_from_cache(self, cache_path: Path) -> bool:
        """Быстрая загрузка словаря из pickle-кэша."""
        try:
            logger.info(f"⚡ Loading dictionary from cache: {cache_path.name}")

            if RICH_AVAILABLE:
                console = Console()
                console.print(
                    Panel(
                        "[bold cyan]⚡ Быстрая загрузка из кэша[/bold cyan]\n"
                        "[dim]Используется предварительно обработанный словарь...[/dim]",
                        title="OpenCorpora Cache",
                    ),
                )

            # Security: This is a locally-generated cache file, not user input
            # Validate file size before loading to prevent memory exhaustion
            import os

            cache_size = os.path.getsize(cache_path)
            if cache_size > 500_000_000:  # 500MB limit
                msg = f"Cache file too large: {cache_size} bytes"
                raise ValueError(msg)

            with open(cache_path, "rb") as f:
                # nosec B301 - This is a locally-generated cache file, not untrusted user input
                cached_data = pickle.load(f)  # nosec B301

            self.dictionary = cached_data["dictionary"]
            cache_info = cached_data.get("metadata", {})

            logger.info(f"✅ Dictionary loaded from cache: {len(self.dictionary):,} entries")
            logger.info(f"📊 Cache created: {cache_info.get('created_at', 'unknown')}")
            logger.info(
                f"🚀 Loading time: ~instant (vs {cache_info.get('original_parse_time', 'N/A')}s from XML)",
            )

            if RICH_AVAILABLE:
                console = Console()
                console.print(
                    Panel(
                        f"[bold green]✅ Словарь загружен из кэша[/bold green]\n"
                        f"[dim]{len(self.dictionary):,} записей • Мгновенная загрузка[/dim]",
                        title="Готово",
                    ),
                )

            return True

        except Exception as e:
            logger.warning(f"⚠️ Failed to load from cache: {e}, will parse XML")
            return False

    def _save_to_cache(self, cache_path: Path, parse_time: float) -> None:
        """Сохранение словаря в pickle-кэш для быстрой загрузки в будущем."""
        try:
            from datetime import datetime

            logger.info(f"💾 Saving dictionary to cache: {cache_path.name}")

            cache_data = {
                "dictionary": self.dictionary,
                "metadata": {
                    "created_at": datetime.now().isoformat(),
                    "entries_count": len(self.dictionary),
                    "original_parse_time": round(parse_time, 2),
                    "mawo_version": "2025.1",
                },
            }

            # Создаем директорию если не существует
            cache_path.parent.mkdir(parents=True, exist_ok=True)

            # Сохраняем с максимальным протоколом pickle
            with open(cache_path, "wb") as f:
                pickle.dump(cache_data, f, protocol=pickle.HIGHEST_PROTOCOL)

            cache_size_mb = cache_path.stat().st_size / (1024 * 1024)
            logger.info(f"✅ Cache saved: {cache_size_mb:.1f} MB")
            logger.info("🚀 Future loads will be instant!")

        except Exception as e:
            logger.warning(f"⚠️ Failed to save cache (non-critical): {e}")

    def _load_dictionary(self) -> None:
        """Загрузка словаря из OpenCorpora XML или кэша."""
        # Проверяем переменную окружения для быстрого режима (тесты)
        import os
        import time

        if os.environ.get("MAWO_FAST_MODE") == "1" or os.environ.get("PYTEST_CURRENT_TEST"):
            logger.info("Fast mode enabled, using basic dictionary")
            self._init_basic_dictionary()
            return

        # Use centralized path configuration
        try:
            from core.path_config import path_config  # type: ignore[import-not-found]

            opencorpora_path = (
                path_config.data_dir
                / "local_libs"
                / "opencorpora_2025"
                / "opencorpora_annot_2025.xml"
            )
        except ImportError:
            # Fallback if path_config is not available
            opencorpora_path = (
                Path(__file__).parent.parent.parent
                / "data"
                / "local_libs"
                / "opencorpora_2025"
                / "opencorpora_annot_2025.xml"
            )

        if opencorpora_path.exists():
            try:
                cache_path = self._get_cache_path(opencorpora_path)

                # Пытаемся загрузить из кэша
                if self._is_cache_valid(opencorpora_path, cache_path):
                    if self._load_from_cache(cache_path):
                        return  # Успешно загружено из кэша!

                # Кэш не найден или устарел - парсим XML
                logger.info("📖 Cache not found or outdated, parsing XML (this will take time...)")

                # Показываем заголовок загрузки
                if RICH_AVAILABLE:
                    console = Console()
                    console.print(
                        Panel(
                            "[bold yellow]📖 Первая загрузка словаря OpenCorpora[/bold yellow]\n"
                            "[dim]Парсинг XML данных • Создание кэша для быстрой загрузки...[/dim]",
                            title="OpenCorpora",
                        ),
                    )

                start_time = time.time()
                self._parse_opencorpora(opencorpora_path)
                parse_time = time.time() - start_time

                # Показываем результат загрузки
                if RICH_AVAILABLE:
                    console = Console()
                    console.print(
                        Panel(
                            f"[bold green]✅ Словарь успешно загружен[/bold green]\n"
                            f"[dim]Обработано {len(self.dictionary):,} записей за {parse_time:.1f}с[/dim]",
                            title="Готово",
                        ),
                    )

                logger.info(
                    f"✅ Loaded OpenCorpora dictionary: {len(self.dictionary):,} entries in {parse_time:.1f}s",
                )

                # Сохраняем в кэш для будущих запусков
                self._save_to_cache(cache_path, parse_time)

            except Exception as e:
                logger.warning(f"Failed to load OpenCorpora: {e}")
                self._init_basic_dictionary()
        else:
            logger.info("OpenCorpora not found, using basic dictionary")
            self._init_basic_dictionary()

    def _process_opencorpora_token(self, token: Any) -> None:
        """Process a single OpenCorpora token and add to dictionary."""
        word_attr = token.get("text")
        if not word_attr:
            return

        word = word_attr.lower()

        # Parse structure: token -> tfr -> v -> l
        for tfr in token.findall("tfr"):
            for v in tfr.findall("v"):
                for lemma in v.findall("l"):
                    normal_form = lemma.get("t", word)

                    # Extract POS from first g element
                    pos = "UNKN"
                    grammemes = set()
                    for gram in lemma.findall("g"):
                        gram_value = gram.get("v")
                        if gram_value:
                            if pos == "UNKN" and gram_value in {
                                "NOUN",
                                "VERB",
                                "ADJF",
                                "ADJS",
                                "COMP",
                                "INFN",
                                "PRTF",
                                "PRTS",
                                "GRND",
                                "NUMR",
                                "ADVB",
                                "NPRO",
                                "PRED",
                                "PREP",
                                "CONJ",
                                "PRCL",
                                "INTJ",
                                "PNCT",
                            }:
                                pos = gram_value
                            else:
                                grammemes.add(gram_value)

                    tag = MAWOTag(pos, grammemes)
                    parse_result = MAWOParse(word, normal_form, tag, 1.0, self)

                    if word not in self.dictionary:
                        self.dictionary[word] = []
                    self.dictionary[word].append(parse_result)

    def _parse_opencorpora(self, xml_path: Path) -> None:
        """Парсинг OpenCorpora XML с прогресс баром."""
        try:
            if ET_PARSE_SAFE:
                tree = defusedxml_parse(xml_path)
            else:
                import xml.etree.ElementTree as ET  # noqa: N817

                tree = ET.parse(xml_path)  # nosec B314
            root = tree.getroot()

            all_tokens = root.findall(".//token")
            total_tokens = len(all_tokens)

            # Используем tqdm для стабильной работы в одну строку
            try:
                from tqdm import tqdm

                if total_tokens > 0:
                    with tqdm(
                        total=total_tokens,
                        desc="📖 Загрузка OpenCorpora словаря",
                        unit="token",
                        dynamic_ncols=True,
                        leave=False,  # Не оставляем прогресс-бар после завершения
                        disable=total_tokens < 1000,  # Отключаем для маленьких словарей
                    ) as pbar:
                        for i, token in enumerate(all_tokens):
                            self._process_opencorpora_token(token)
                            if (i + 1) % 100 == 0:
                                pbar.update(100)
                        # Обновляем до конца если остались необработанные токены
                        pbar.update(total_tokens - pbar.n)
                else:
                    for token in all_tokens:
                        self._process_opencorpora_token(token)
            except ImportError:
                # Fallback без прогресс-бара если tqdm не доступен
                for token in all_tokens:
                    self._process_opencorpora_token(token)

        except Exception as e:
            logger.exception(f"Error parsing OpenCorpora: {e}")
            raise

    def _init_basic_dictionary(self) -> None:
        """Базовый словарь для fail_fast_mode."""
        basic_words = {
            # Местоимения
            "я": [("я", "NPRO", {"sing", "1per", "nomn"})],
            "ты": [("ты", "NPRO", {"sing", "2per", "nomn"})],
            "он": [("он", "NPRO", {"sing", "3per", "masc", "nomn"})],
            "она": [("она", "NPRO", {"sing", "3per", "femn", "nomn"})],
            "оно": [("оно", "NPRO", {"sing", "3per", "neut", "nomn"})],
            "мы": [("мы", "NPRO", {"plur", "1per", "nomn"})],
            "вы": [("вы", "NPRO", {"plur", "2per", "nomn"})],
            "они": [("они", "NPRO", {"plur", "3per", "nomn"})],
            # Глаголы
            "быть": [("быть", "INFN", {"impf"})],
            "есть": [("быть", "VERB", {"pres", "3per", "sing"})],
            "был": [("быть", "VERB", {"past", "masc", "sing"})],
            "была": [("быть", "VERB", {"past", "femn", "sing"})],
            "было": [("быть", "VERB", {"past", "neut", "sing"})],
            "были": [("быть", "VERB", {"past", "plur"})],
            # Существительные
            "дом": [("дом", "NOUN", {"masc", "inan", "nomn", "sing"})],
            "дома": [
                ("дом", "NOUN", {"masc", "inan", "gent", "sing"}),
                ("дом", "NOUN", {"masc", "inan", "nomn", "plur"}),
            ],
            "школа": [("школа", "NOUN", {"femn", "inan", "nomn", "sing"})],
            "школы": [
                ("школа", "NOUN", {"femn", "inan", "gent", "sing"}),
                ("школа", "NOUN", {"femn", "inan", "nomn", "plur"}),
            ],
        }

        for word, forms in basic_words.items():
            self.dictionary[word] = []
            for normal_form, pos, grammemes in forms:
                tag = MAWOTag(pos, grammemes)
                parse_result = MAWOParse(word, normal_form, tag, 0.8, self)
                self.dictionary[word].append(parse_result)

    def _init_patterns(self) -> None:
        """Инициализация морфологических паттернов."""
        self.patterns = {
            # Окончания существительных
            "noun_endings": {
                "а": ("femn", "nomn", "sing"),
                "ы": ("femn", "nomn", "plur"),
                "ой": ("femn", "gent", "sing"),
                "ем": ("masc", "ablt", "sing"),
                "ами": ("femn", "ablt", "plur"),
            },
            # Окончания глаголов
            "verb_endings": {
                "ть": ("INFN", set()),
                "ти": ("INFN", set()),
                "чь": ("INFN", set()),
                "ет": ("VERB", {"3per", "sing", "pres"}),
                "ут": ("VERB", {"3per", "plur", "pres"}),
                "ют": ("VERB", {"3per", "plur", "pres"}),
            },
            # Окончания прилагательных
            "adj_endings": {
                "ый": ("ADJF", {"masc", "nomn", "sing"}),
                "ий": ("ADJF", {"masc", "nomn", "sing"}),
                "ой": ("ADJF", {"masc", "nomn", "sing"}),
                "ая": ("ADJF", {"femn", "nomn", "sing"}),
                "яя": ("ADJF", {"femn", "nomn", "sing"}),
                "ое": ("ADJF", {"neut", "nomn", "sing"}),
                "ее": ("ADJF", {"neut", "nomn", "sing"}),
            },
        }

    def parse(self, word: str) -> list[MAWOParse]:
        """Морфологический анализ слова.

        Args:
            word: Слово для анализа

        Returns:
            Список возможных разборов слова

        """
        if not word or not word.strip():
            return []

        word_clean = word.lower().strip()

        # Если используем DAWG через pymorphy2
        if self.use_dawg and self._pymorphy2_analyzer:
            try:
                pymorphy_parses = self._pymorphy2_analyzer.parse(word_clean)

                # Конвертируем pymorphy2 Parse в MAWOParse
                mawo_parses = []
                for p in pymorphy_parses:
                    # Извлекаем POS и граммемы из pymorphy2 тега
                    pos = str(p.tag.POS) if hasattr(p.tag, "POS") else "UNKN"
                    grammemes = (
                        set(str(g) for g in p.tag.grammemes)
                        if hasattr(p.tag, "grammemes")
                        else set()
                    )

                    mawo_tag = MAWOTag(pos, grammemes)
                    mawo_parse = MAWOParse(
                        word=word_clean,
                        normal_form=p.normal_form,
                        tag=mawo_tag,
                        score=p.score,
                        analyzer=self,
                    )
                    mawo_parses.append(mawo_parse)

                return mawo_parses

            except Exception as e:
                logger.warning(f"Ошибка при разборе через pymorphy2: {e}")
                # Fallback к обычному методу

        # Fallback: сначала ищем в словаре
        if word_clean in self.dictionary:
            # Добавляем ссылку на анализатор для inflect()
            parses = self.dictionary[word_clean]
            for parse in parses:
                parse._analyzer = self
            return parses

        # Если не найдено, используем паттерны
        return self._analyze_by_patterns(word_clean)

    def _analyze_by_patterns(self, word: str) -> list[MAWOParse]:
        """Анализ слова по морфологическим паттернам."""
        results: list[Any] = []

        # Проверяем окончания глаголов
        for ending, (pos, grammemes) in self.patterns["verb_endings"].items():
            if word.endswith(ending) and len(word) > len(ending):
                normal_form = word[: -len(ending)] + "ть" if pos == "INFN" else word
                tag = MAWOTag(pos, grammemes)
                results.append(MAWOParse(word, normal_form, tag, 0.6, self))

        # Проверяем окончания прилагательных
        for ending, (pos, grammemes) in self.patterns["adj_endings"].items():
            if word.endswith(ending) and len(word) > len(ending):
                normal_form = word[: -len(ending)] + "ый"
                tag = MAWOTag(pos, grammemes)
                results.append(MAWOParse(word, normal_form, tag, 0.6, self))

        # Проверяем окончания существительных
        for ending, (gender, case, number) in self.patterns["noun_endings"].items():
            if word.endswith(ending) and len(word) > len(ending):
                normal_form = word  # Упрощенно - нужно правильное восстановление
                grammemes = {gender, case, number, "inan"}
                tag = MAWOTag("NOUN", grammemes)
                results.append(MAWOParse(word, normal_form, tag, 0.4, self))

        # Если ничего не найдено, возвращаем неизвестное слово
        if not results:
            tag = MAWOTag("UNKN", set())
            results.append(MAWOParse(word, word, tag, 0.1, self))

        return results


class MAWOOptimizedMorphAnalyzer:
    """Оптимизированный морфологический анализатор для MAWO системы
    Интерфейс для совместимости с методами обучения.
    """

    def __init__(self, dict_path: str | None = None) -> None:
        self.base_analyzer = create_analyzer(dict_path)
        self.cache: dict[str, list[dict[str, Any]]] = {}
        logger.info("✅ MAWOOptimizedMorphAnalyzer initialized")

    def analyze(self, text: str) -> list[dict[str, Any]]:
        """Анализ текста с кэшированием результатов.

        Args:
            text: Текст для анализа

        Returns:
            Список словарей с результатами анализа

        """
        if not text:
            return []

        if text in self.cache:
            return self.cache[text]

        words = text.split()
        results: list[Any] = []

        for word in words:
            if word.isalpha():
                parses = self.base_analyzer.parse(word)
                if parses:
                    best_parse = parses[0]  # Берем лучший разбор
                    results.append(
                        {
                            "word": word,
                            "normal_form": best_parse.normal_form,
                            "pos": best_parse.tag.POS,
                            "case": best_parse.tag.case,
                            "number": best_parse.tag.number,
                            "gender": best_parse.tag.gender,
                            "aspect": best_parse.tag.aspect,
                            "tense": best_parse.tag.tense,
                            "score": best_parse.score,
                            "analysis_mode": "mawo_morphology",
                        },
                    )

        # Кэшируем результат
        self.cache[text] = results
        return results


def create_analyzer(dict_path: str | None = None, use_dawg: bool = True) -> MAWOMorphAnalyzer:
    """Создает морфологический анализатор MAWO (синглтон).

    ВАЖНО: Использует DAWG словари для быстрой загрузки и малого потребления памяти.
    - Загрузка: ~1-2 секунды
    - Память: ~15-20 МБ (вместо ~500 МБ)
    - Thread-safe реализация с double-checked locking

    Args:
        dict_path: Путь к словарю (опционально, по умолчанию dicts_ru/)
        use_dawg: Использовать DAWG оптимизацию (по умолчанию True)

    Returns:
        Экземпляр MAWOMorphAnalyzer (синглтон в рамках процесса)

    """
    global _GLOBAL_ANALYZER_INSTANCE, _ANALYZER_LOCK

    # Быстрая проверка без блокировки
    if _GLOBAL_ANALYZER_INSTANCE is not None:
        logger.debug("⚡ Returning existing singleton analyzer instance (fast path)")  # type: ignore[unreachable]
        return _GLOBAL_ANALYZER_INSTANCE

    # Медленный путь с блокировкой
    if _ANALYZER_LOCK:
        with _ANALYZER_LOCK:
            # Double-checked locking: проверяем снова внутри блокировки
            if _GLOBAL_ANALYZER_INSTANCE is None:
                logger.info("🔄 Creating new singleton analyzer instance (thread-safe)")
                _GLOBAL_ANALYZER_INSTANCE = MAWOMorphAnalyzer(dict_path, use_dawg=use_dawg)
            else:
                logger.debug("⚡ Another thread created instance, using it")  # type: ignore[unreachable]
    # PRODUCTION REQUIRED без threading (fallback для старых систем)
    elif _GLOBAL_ANALYZER_INSTANCE is None:
        logger.info("🔄 Creating new singleton analyzer instance (no threading)")
        _GLOBAL_ANALYZER_INSTANCE = MAWOMorphAnalyzer(dict_path, use_dawg=use_dawg)

    return _GLOBAL_ANALYZER_INSTANCE


def get_global_analyzer() -> MAWOMorphAnalyzer:
    """Получение глобального экземпляра морфологического анализатора (синглтон).

    Эта функция эквивалентна create_analyzer() без параметров,
    но явно подчеркивает что возвращается глобальный синглтон.

    Returns:
        Глобальный экземпляр MAWOMorphAnalyzer
    """
    return create_analyzer()


class MAWODictionaryManager:
    """Менеджер для управления DAWG кэшем и словарями OpenCorpora."""

    def __init__(self, dict_path: Path | None = None) -> None:
        """Инициализация менеджера словарей.

        Args:
            dict_path: Путь к директории со словарями (опционально)
        """
        if dict_path is None:
            dict_path = Path(__file__).parent / "dicts_ru"
        self.dict_path = Path(dict_path)
        self.dawg_cache_path = self.dict_path / "words.dawg"

    def is_dawg_cache_available(self) -> bool:
        """Проверяет наличие DAWG кэша.

        Returns:
            True если DAWG словарь существует
        """
        return self.dawg_cache_path.exists()

    def build_dawg_cache(self) -> bool:
        """Создает DAWG кэш из OpenCorpora XML.

        Returns:
            True если кэш успешно создан
        """
        logger.info("🔨 Building DAWG cache from OpenCorpora XML...")

        try:
            # Импортируем DAWG optimizer
            from .dawg_optimizer import get_dawg_optimizer

            optimizer = get_dawg_optimizer()

            if not optimizer.is_available():
                logger.error("❌ DAWG library not available. Install with: pip install dawg-python")
                return False

            # Создаем временный анализатор для загрузки словаря
            analyzer = MAWOMorphAnalyzer()

            # Конвертируем словарь в DAWG
            dawg_dict = optimizer.convert_dict_to_dawg(analyzer.dictionary)

            # Сохраняем DAWG кэш
            optimizer.save_dawg_cache(dawg_dict, self.dawg_cache_path)

            logger.info("✅ DAWG cache built successfully!")
            return True

        except Exception as e:
            logger.exception(f"❌ Failed to build DAWG cache: {e}")
            return False

    def get_cache_info(self) -> dict[str, Any]:
        """Получение информации о кэше.

        Returns:
            Словарь с информацией о кэше
        """
        info: dict[str, Any] = {
            "dict_path": str(self.dict_path),
            "dawg_available": self.is_dawg_cache_available(),
        }

        if self.is_dawg_cache_available():
            info["dawg_size_mb"] = self.dawg_cache_path.stat().st_size / (1024 * 1024)

        return info


# Экспорт для совместимости с pymorphy3
MorphAnalyzer = MAWOMorphAnalyzer

# Основные экспорты
__all__ = [
    "MAWOMorphAnalyzer",
    "MAWOOptimizedMorphAnalyzer",
    "MAWOParse",
    "MAWOTag",
    "MorphAnalyzer",
    "create_analyzer",
    "get_global_analyzer",
    "MAWODictionaryManager",
]
