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

    # Mapping редких падежей на обычные (как в pymorphy2)
    RARE_CASES = {
        "gen1": "gent",
        "gen2": "gent",
        "acc1": "accs",
        "acc2": "accs",
        "loc1": "loct",
        "loc2": "loct",
        "voct": "nomn",
    }

    def __init__(self, pos: str = "UNKN", grammemes: set[str] | None = None) -> None:
        self.POS = pos
        self.grammemes = grammemes or set()

    @classmethod
    def fix_rare_cases(cls, grammemes: set[str]) -> set[str]:
        """
        Replace rare cases (loc2/voct/...) with common ones (loct/nomn/...).
        Как в pymorphy2.
        """
        return {cls.RARE_CASES.get(g, g) for g in grammemes}

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

    def __eq__(self, other: Any) -> bool:
        """Проверка равенства тегов."""
        if not isinstance(other, MAWOTag):
            return False
        return self.POS == other.POS and self.grammemes == other.grammemes

    def __hash__(self) -> int:
        """Хеш тега для использования в set/dict."""
        return hash((self.POS, frozenset(self.grammemes)))


class MAWOParse:
    """Результат морфологического анализа."""

    def __init__(
        self,
        word: str,
        normal_form: str,
        tag: MAWOTag,
        score: float = 1.0,
        analyzer: Any | None = None,
        paradigm_id: int | None = None,
        stem: str | None = None,
    ) -> None:
        self.word = word
        self.normal_form = normal_form
        self.tag = tag
        self.score = score
        self._analyzer = analyzer
        self._paradigm_id = paradigm_id
        self._stem = stem

    def inflect(self, required_grammemes: set[str]) -> MAWOParse | None:
        """Получение словоформы с заданными грамматическими признаками.

        Алгоритм как в pymorphy2:
        1. Получить лексему (все формы слова)
        2. Найти формы, содержащие требуемые граммемы
        3. Выбрать наиболее похожую форму

        Args:
            required_grammemes: Множество требуемых граммем (например, {"sing", "femn"})

        Returns:
            MAWOParse с нужными граммемами или None если не найдено
        """
        if not self._analyzer:
            logger.warning("Analyzer not available for inflection")
            return None

        # Получаем лексему (все формы слова)
        lexeme = self.lexeme

        # Ищем формы, содержащие требуемые граммемы (сначала с исходными редкими падежами)
        possible_results = []
        for form in lexeme:
            form_tags = form.tag.grammemes | {form.tag.POS}
            if required_grammemes.issubset(form_tags):
                possible_results.append(form)

        # Если ничего не найдено с редкими падежами, пробуем нормализовать
        if not possible_results:
            normalized_grammemes = MAWOTag.fix_rare_cases(required_grammemes)
            # Если нормализация что-то изменила, пробуем еще раз
            if normalized_grammemes != required_grammemes:
                for form in lexeme:
                    form_tags = form.tag.grammemes | {form.tag.POS}
                    if normalized_grammemes.issubset(form_tags):
                        possible_results.append(form)

        # Если ничего не найдено, возвращаем None
        if not possible_results:
            return None

        # Если найдена одна форма, возвращаем ее
        if len(possible_results) == 1:
            return possible_results[0]

        # Если несколько форм, выбираем наиболее похожую
        # Логика similarity из pymorphy2:
        # similarity = len(common_grammemes) - 0.1 * len(symmetric_difference)
        source_grammemes = self.tag.grammemes | {self.tag.POS}

        def similarity(form: MAWOParse) -> float:
            form_grammemes = form.tag.grammemes | {form.tag.POS}
            common = source_grammemes & form_grammemes
            diff = source_grammemes ^ form_grammemes
            return len(common) - 0.1 * len(diff)

        # Возвращаем форму с максимальной similarity
        return max(possible_results, key=similarity)

    def _inflect_legacy(self, required_grammemes: set[str]) -> MAWOParse | None:
        """Старый метод inflect (оставлен для справки).

        Использовался до реализации lexeme-based подхода.
        """
        if not self._analyzer:
            logger.warning("Analyzer not available for inflection")
            return None

        # Если используется DAWG и есть paradigm_id
        if (
            hasattr(self._analyzer, "_dawg_dict")
            and self._analyzer._dawg_dict
            and self._paradigm_id is not None
            and self._stem is not None
        ):
            # Получаем все формы парадигмы
            paradigm_forms = self._analyzer._dawg_dict.get_all_paradigm_forms(self._paradigm_id)

            # Группируем граммемы по категориям
            def get_grammeme_groups():
                return {
                    "number": {"sing", "plur"},
                    "tense": {"past", "pres", "futr"},
                    "gender": {"masc", "femn", "neut"},
                    "case": {
                        "nomn",
                        "gent",
                        "datv",
                        "accs",
                        "ablt",
                        "loct",
                        "voct",
                        "gen2",
                        "acc2",
                        "loc2",
                    },
                    "person": {"1per", "2per", "3per"},
                    "aspect": {"perf", "impf"},
                    "voice": {"actv", "pssv"},
                    "animacy": {"anim", "inan"},
                }

            # Определяем, какие граммемы из исходного слова нужно сохранить
            source_grammemes_to_preserve = set()
            grammeme_groups = get_grammeme_groups()

            # Для некоторых частей речи не нужно сохранять определенные граммемы
            # GRND (деепричастие) - не имеет рода, числа, лица, падежа (но ИМЕЕТ время: past/pres)
            # INFN (инфинитив) - не имеет времени, рода, числа, лица, падежа
            # COMP (сравнительная степень) - не имеет рода, числа, падежа
            pos_incompatible_groups = {
                "GRND": {"gender", "number", "person", "case"},
                "INFN": {"tense", "gender", "number", "person", "case"},
                "COMP": {"gender", "number", "case"},
                "PRTS": {"case"},  # Краткое причастие - нет падежа
                "ADJS": {"case"},  # Краткое прилагательное - нет падежа
            }

            # Определяем целевой POS (из required_grammemes или из текущего тега)
            target_pos = None
            pos_set = {
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
            }
            for pos_candidate in required_grammemes & pos_set:
                target_pos = pos_candidate
                break

            for group_name, group_grammemes in grammeme_groups.items():
                # Пропускаем группы, несовместимые с целевым POS
                if target_pos and target_pos in pos_incompatible_groups:
                    if group_name in pos_incompatible_groups[target_pos]:
                        continue

                # Если в required_grammemes нет граммем этой группы, берем из исходного
                if not (required_grammemes & group_grammemes):
                    source_grammemes_to_preserve.update(self.tag.grammemes & group_grammemes)

            # Объединяем требуемые граммемы с сохраняемыми из исходного слова
            target_grammemes = required_grammemes | source_grammemes_to_preserve

            # Ищем форму с нужными граммемами
            for suffix, tag_string, prefix in paradigm_forms:
                pos, grammemes = self._analyzer._dawg_dict.parse_tag_string(tag_string)

                # Проверяем совпадение граммем И/ИЛИ POS
                all_tags = grammemes | {pos}
                if target_grammemes.issubset(all_tags):
                    # Собираем слово
                    inflected_word = prefix + self._stem + suffix

                    # Создаем новый parse
                    new_tag = MAWOTag(pos, grammemes)
                    return MAWOParse(
                        word=inflected_word,
                        normal_form=self.normal_form,
                        tag=new_tag,
                        score=self.score,
                        analyzer=self._analyzer,
                        paradigm_id=self._paradigm_id,
                        stem=self._stem,
                    )

            # Если точное совпадение не найдено, ищем частичное
            best_match = None
            best_match_score = 0

            for suffix, tag_string, prefix in paradigm_forms:
                pos, grammemes = self._analyzer._dawg_dict.parse_tag_string(tag_string)

                all_tags = grammemes | {pos}
                matching_grammemes = all_tags & target_grammemes
                match_score = len(matching_grammemes)

                if match_score > best_match_score:
                    best_match_score = match_score
                    inflected_word = prefix + self._stem + suffix
                    new_tag = MAWOTag(pos, grammemes)
                    best_match = MAWOParse(
                        word=inflected_word,
                        normal_form=self.normal_form,
                        tag=new_tag,
                        score=self.score,
                        analyzer=self._analyzer,
                        paradigm_id=self._paradigm_id,
                        stem=self._stem,
                    )

            return best_match

        # Fallback для обычного словаря
        if hasattr(self._analyzer, "dictionary"):
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

    @property
    def is_known(self) -> bool:
        """Проверить, известно ли слово словарю.

        Returns:
            True если слово найдено в словаре, False если предсказано
        """
        # Если у нас есть paradigm_id, значит слово из DAWG словаря
        if self._paradigm_id is not None:
            return True

        # Проверяем через анализатор
        if self._analyzer and hasattr(self._analyzer, "_dawg_dict") and self._analyzer._dawg_dict:
            return self._analyzer._dawg_dict.word_is_known(self.word)

        # Fallback: проверяем score (предсказанные слова имеют score < 1.0)
        return self.score >= 1.0

    @property
    def normalized(self) -> MAWOParse:
        """Получить разбор нормальной формы слова.

        Returns:
            MAWOParse для нормальной формы
        """
        if self.word == self.normal_form:
            return self

        # Парсим нормальную форму
        if self._analyzer:
            parses = self._analyzer.parse(self.normal_form)
            if parses:
                # Ищем разбор с тем же POS
                for p in parses:
                    if p.tag.POS == self.tag.POS:
                        return p
                # Если не нашли с тем же POS, возвращаем первый
                return parses[0]

        # Fallback: создаем parse для нормальной формы
        return MAWOParse(
            word=self.normal_form,
            normal_form=self.normal_form,
            tag=self.tag,
            score=self.score,
            analyzer=self._analyzer,
            paradigm_id=self._paradigm_id,
            stem=self._stem,
        )

    def make_agree_with_number(self, num: int) -> MAWOParse | None:
        """Согласовать слово с числительным.

        Args:
            num: Число для согласования

        Returns:
            Согласованная форма или None
        """
        # Определяем нужное число (единственное или множественное)
        # Правила русского языка:
        # 1 - sing (1 дом)
        # 2,3,4 - sing + gent (2 дома, но в некоторых случаях это особая форма)
        # 5+ - plur + gent (5 домов)
        # 11-14 - особый случай, всегда plur + gent

        if num % 10 == 1 and num % 100 != 11:
            # 1, 21, 31, ... - единственное число, именительный падеж
            return self.inflect({"sing", "nomn"})
        elif 2 <= num % 10 <= 4 and (num % 100 < 10 or num % 100 >= 20):
            # 2,3,4, 22,23,24, ... - единственное число, родительный падеж
            return self.inflect({"sing", "gent"})
        else:
            # 5-20, 25-30, ... - множественное число, родительный падеж
            return self.inflect({"plur", "gent"})

    @property
    def methods_stack(self) -> tuple:
        """Стек методов разбора (для совместимости с pymorphy2).

        Returns:
            Пустой кортеж (заглушка)
        """
        # В pymorphy2 это список методов, использованных для разбора
        # Для нас это не критично, возвращаем пустой tuple
        return ()

    @property
    def lexeme(self) -> list[MAWOParse]:
        """Получить все формы слова (лексему/парадигму).

        Returns:
            Список всех словоформ данного слова
        """
        if not self._analyzer:
            return [self]

        # Проверяем, есть ли частица в normal_form (для слов типа "сказать-ка")
        particle_suffix = None
        if "-" in self.normal_form:
            particles = ["ка", "то", "таки", "де", "тко", "тка", "с", "ста"]
            parts = self.normal_form.rsplit("-", 1)
            if len(parts) == 2 and parts[1] in particles:
                particle_suffix = "-" + parts[1]

        # Если используется DAWG и есть paradigm_id
        if (
            hasattr(self._analyzer, "_dawg_dict")
            and self._analyzer._dawg_dict
            and self._paradigm_id is not None
            and self._stem is not None
        ):
            lexeme_forms = []
            paradigm_forms = self._analyzer._dawg_dict.get_all_paradigm_forms(self._paradigm_id)

            for suffix, tag_string, prefix in paradigm_forms:
                pos, grammemes = self._analyzer._dawg_dict.parse_tag_string(tag_string)
                inflected_word = prefix + self._stem + suffix

                # Определяем нормальную форму (первая форма парадигмы)
                normal_form_info = self._analyzer._dawg_dict.get_paradigm(self._paradigm_id, 0)
                if normal_form_info:
                    normal_suffix, _, normal_prefix = normal_form_info
                    normal_form = normal_prefix + self._stem + normal_suffix
                else:
                    normal_form = inflected_word

                # Добавляем частицу обратно если она была
                if particle_suffix:
                    inflected_word = inflected_word + particle_suffix
                    normal_form = normal_form + particle_suffix

                new_tag = MAWOTag(pos, grammemes)
                lexeme_forms.append(
                    MAWOParse(
                        word=inflected_word,
                        normal_form=normal_form,
                        tag=new_tag,
                        score=self.score,
                        analyzer=self._analyzer,
                        paradigm_id=self._paradigm_id,
                        stem=self._stem,
                    )
                )

            return lexeme_forms

        # Fallback для обычного словаря
        if hasattr(self._analyzer, "dictionary"):
            normal_forms = self._analyzer.dictionary.get(self.normal_form, [])
            return normal_forms if normal_forms else [self]

        return [self]

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
        self._dawg_dict: Any = None

        # Используем собственный DAWGDictionary если указано
        if self.use_dawg and Path(self.dict_path).exists():
            try:
                from .dawg_dictionary import DAWGDictionary

                logger.info("⚡ Загрузка DAWG словарей...")
                self._dawg_dict = DAWGDictionary(self.dict_path)
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

            except ImportError as e:
                logger.error(f"⚠️ dawg-python не установлен: {e}, используем fallback")
                logger.exception("Полная трассировка ImportError:")
                self.use_dawg = False
            except Exception as e:
                logger.error(f"⚠️ Ошибка загрузки DAWG: {e}, используем fallback")
                logger.exception("Полная трассировка ошибки:")
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

        # Пытаемся сначала с исходным словом
        result = self._parse_word(word_clean)

        # Е/Ё нормализация (best practice NLP 2024-2025):
        # Для оптимизации производительности, пробуем альтернативное написание только если:
        # 1. Есть е или ё в слове
        # 2. И хотя бы одно из условий:
        #    - Нет результата вообще
        #    - Результат UNKN
        #    - Результат предсказанный (score < 1.0)
        #    - Результат не NOUN/VERB/ADJF (низкоприоритетный POS)

        should_try_normalization = False
        if "е" in word_clean or "ё" in word_clean:
            if not result:
                should_try_normalization = True
            else:
                # Проверяем качество первого результата
                first = result[0]
                high_priority_pos = {"NOUN", "VERB", "INFN", "ADJF"}
                if (first.tag.POS == "UNKN" or
                    first.score < 1.0 or
                    first.tag.POS not in high_priority_pos):
                    should_try_normalization = True

        if should_try_normalization:
            # Заменяем е ↔ ё
            word_normalized = word_clean.replace("е", "\x00").replace("ё", "е").replace("\x00", "ё")
            result_normalized = self._parse_word(word_normalized)

            if result_normalized:
                # Восстанавливаем оригинальное написание
                for parse in result_normalized:
                    parse.word = word_clean

                # Объединяем результаты, удаляя дубликаты
                seen = set()
                combined = []
                for parse in result + result_normalized:
                    key = (parse.normal_form, str(parse.tag))
                    if key not in seen:
                        seen.add(key)
                        combined.append(parse)
                result = combined

        # Применяем эвристику для сортировки разборов (лучшие первыми)
        # Приоритет: словарные > POS (NOUN > VERB > ADJF) > nominative > меньше граммем
        if result and len(result) > 1:
            result = self._rank_parses(result)

        return result if result else []

    def _rank_parses(self, parses: list[MAWOParse]) -> list[MAWOParse]:
        """Ранжировать разборы по эвристикам (лучшие первыми).

        Эвристики (в порядке приоритета - по best practices NLP 2024-2025):
        1. Словарные слова (score >= 1.0) ВСЕГДА лучше предсказанных (score < 1.0)
        2. Среди словарных: Часть речи: NOUN > VERB > ADJF > остальные
        3. Именительный падеж (nomn) предпочтительнее косвенных
        4. Меньше граммем = проще форма = вероятнее

        Args:
            parses: Список разборов

        Returns:
            Отсортированный список разборов
        """

        def parse_rank(p: MAWOParse) -> tuple[int, int, int, int]:
            # Приоритет 0: словарные слова vs предсказанные
            # Это КРИТИЧНО: словарные ВСЕГДА лучше предсказанных
            is_predicted = 1 if p.score < 1.0 else 0

            # Приоритет 1: POS (только среди словарных или среди предсказанных)
            # Основано на частотности частей речи в русском языке
            pos_priority = {
                "NOUN": 0,  # Существительные - самый частый класс
                "VERB": 1,  # Глаголы
                "INFN": 1,  # Инфинитивы (тоже глаголы)
                "ADJF": 2,  # Прилагательные полные
                "NUMR": 2,  # Числительные
                "NPRO": 2,  # Местоимения-существительные
                "ADJS": 3,  # Прилагательные краткие
                "ADVB": 3,  # Наречия
                "PRTF": 3,  # Причастия полные
                "PRTS": 4,  # Причастия краткие
                "GRND": 4,  # Деепричастия
                "PRED": 4,  # Предикативы
            }
            pos_rank = pos_priority.get(p.tag.POS, 10)

            # Приоритет 2: nominative case (именительный падеж чаще встречается)
            nomn_penalty = 0 if "nomn" in p.tag.grammemes else 1

            # Приоритет 3: меньше граммем = проще форма
            grammemes_count = len(p.tag.grammemes)

            return (is_predicted, pos_rank, nomn_penalty, grammemes_count)

        return sorted(parses, key=parse_rank)

    def tag(self, word: str) -> list[MAWOTag]:
        """Получить список возможных тегов для слова.

        Args:
            word: Слово для анализа

        Returns:
            Список возможных тегов (MAWOTag)
        """
        parses = self.parse(word)
        return [p.tag for p in parses]

    def _parse_word(self, word_clean: str) -> list[MAWOParse]:
        """Внутренний метод парсинга слова без е/ё нормализации."""

        # Сначала пробуем стандартный парсинг
        result = self._parse_word_base(word_clean)

        # Если получили хороший результат (не UNKN и не предсказание), возвращаем его
        # Предсказания имеют score < 1.0
        if result and result[0].tag.POS != "UNKN" and result[0].score >= 1.0:
            return result

        # HyphenSeparatedParticleAnalyzer: обработка слов с частицами после дефиса
        # Только если стандартный парсинг дал UNKN или предсказание
        if "-" in word_clean:
            particles = ["-ка", "-то", "-таки", "-де", "-тко", "-тка", "-с", "-ста"]
            for particle in particles:
                if word_clean.endswith(particle):
                    # Парсим слово без частицы
                    word_without_particle = word_clean[: -len(particle)]
                    if word_without_particle:
                        parses = self._parse_word_base(word_without_particle)
                        if parses and parses[0].tag.POS != "UNKN":
                            # Добавляем частицу обратно
                            particle_result = []
                            for p in parses:
                                new_parse = MAWOParse(
                                    word=word_clean,  # с частицей
                                    normal_form=p.normal_form + particle,
                                    tag=p.tag,
                                    score=p.score * 0.9,  # score_multiplier
                                    analyzer=self,
                                    paradigm_id=p._paradigm_id,
                                    stem=p._stem,
                                )
                                particle_result.append(new_parse)
                            return particle_result
                    break  # Только одна частица может быть

        # Возвращаем результат стандартного парсинга (может быть UNKN)
        return result if result else []

    def _parse_word_base(self, word_clean: str) -> list[MAWOParse]:
        """Базовый парсинг слова без обработки частиц."""

        # ========== SPECIAL ANALYZERS (Best Practice NLP 2024-2025) ==========
        # Обрабатываем специальные токены ДО морфологического анализа
        # Подход основан на spaCy tokenizer special cases

        # 1. PunctuationAnalyzer - знаки пунктуации
        if self._is_punctuation(word_clean):
            return [
                MAWOParse(
                    word=word_clean,
                    normal_form=word_clean,
                    tag=MAWOTag("PNCT", set()),
                    score=1.0,
                    analyzer=self,
                )
            ]

        # 2. NumberAnalyzer - числа
        number_result = self._analyze_number(word_clean)
        if number_result:
            return number_result

        # 3. RomanNumeralAnalyzer - римские цифры
        # 4. LatinAnalyzer - латинский текст (не содержит кириллицу)
        # Некоторые токены могут быть и римскими цифрами, и латинским текстом
        # (например, "I", "V", "X", "L", "C", "D", "M")
        special_results = []

        roman_result = self._analyze_roman(word_clean)
        if roman_result:
            special_results.extend(roman_result)

        if self._is_latin(word_clean):
            # Добавляем LATN вариант
            special_results.append(
                MAWOParse(
                    word=word_clean,
                    normal_form=word_clean.lower(),
                    tag=MAWOTag("LATN", set()),
                    score=1.0,
                    analyzer=self,
                )
            )

        if special_results:
            return special_results

        # ========== MORPHOLOGICAL ANALYSIS ==========
        # Если используем DAWG через DAWGDictionary
        if self.use_dawg and self._dawg_dict:
            try:
                # Получаем разборы слова из DAWG
                word_parses = self._dawg_dict.get_word_parses(word_clean)

                mawo_parses = []
                for paradigm_id, word_idx in word_parses:
                    # Получаем информацию о парадигме
                    paradigm_info = self._dawg_dict.get_paradigm(paradigm_id, word_idx)

                    if paradigm_info is None:
                        continue

                    suffix, tag_string, prefix = paradigm_info

                    # Разбираем тег
                    pos, grammemes = self._dawg_dict.parse_tag_string(tag_string)

                    # Вычисляем нормальную форму
                    # Получаем первую форму парадигмы (word_idx=0)
                    normal_form_info = self._dawg_dict.get_paradigm(paradigm_id, 0)
                    if normal_form_info:
                        normal_suffix, _, normal_prefix = normal_form_info
                        # Извлекаем основу (stem)
                        # Удаляем префикс и суффикс из текущего слова
                        stem = word_clean
                        if prefix and stem.startswith(prefix):
                            stem = stem[len(prefix) :]
                        if suffix and stem.endswith(suffix):
                            stem = stem[: -len(suffix)]

                        # Собираем нормальную форму
                        normal_form = normal_prefix + stem + normal_suffix
                    else:
                        normal_form = word_clean

                    mawo_tag = MAWOTag(pos, grammemes)
                    mawo_parse = MAWOParse(
                        word=word_clean,
                        normal_form=normal_form,
                        tag=mawo_tag,
                        score=1.0,
                        analyzer=self,
                        paradigm_id=paradigm_id,
                        stem=stem if normal_form_info else None,
                    )
                    mawo_parses.append(mawo_parse)

                if mawo_parses:
                    return mawo_parses

            except Exception as e:
                logger.warning(f"Ошибка при разборе через DAWG: {e}")
                # Fallback к обычному методу

        # Fallback: сначала ищем в словаре
        if word_clean in self.dictionary:
            # Добавляем ссылку на анализатор для inflect()
            parses = self.dictionary[word_clean]
            for parse in parses:
                parse._analyzer = self
            return parses

        # Если не найдено, пробуем предсказание по суффиксам (KnownSuffixAnalyzer)
        if self.use_dawg and self._dawg_dict:
            predicted = self._predict_by_suffix(word_clean)
            if predicted:
                return predicted

        # Если не найдено, используем паттерны
        return self._analyze_by_patterns(word_clean)

    def _predict_by_suffix(self, word: str) -> list[MAWOParse]:
        """Предсказание форм слова по известным суффиксам (упрощённый KnownSuffixAnalyzer)."""
        if len(word) < 4:
            return []

        results = []

        # Пробуем разные длины суффиксов (от 4 до 2 символов)
        for suffix_len in [4, 3, 2]:
            if len(word) <= suffix_len:
                continue

            suffix = word[-suffix_len:]

            # Ищем слова с таким же суффиксом в DAWG
            similar_words = []
            try:
                # Простой поиск: проверяем несколько вариантов
                for test_stem in [
                    "к",
                    "м",
                    "п",
                    "т",
                    "л",
                    "н",
                    "р",
                    "с",
                    "в",
                    "д",
                    "б",
                    "г",
                    "з",
                    "ж",
                    "х",
                ]:
                    test_word = test_stem + suffix
                    word_parses = self._dawg_dict.get_word_parses(test_word)
                    if word_parses:
                        similar_words.append((test_word, word_parses[0]))
                        if len(similar_words) >= 3:
                            break
            except Exception:
                pass

            # Если нашли похожие слова, используем их парадигму
            if similar_words:
                # Берём первое похожее слово
                similar_word, (paradigm_id, word_idx) = similar_words[0]

                # Определяем stem нового слова
                # Нужно вычесть суффикс из похожего слова и заменить на наш stem
                paradigm_info = self._dawg_dict.get_paradigm(paradigm_id, word_idx)
                if paradigm_info:
                    suffix_old, tag_string, prefix = paradigm_info

                    # Вычисляем stem похожего слова
                    similar_stem = similar_word
                    if prefix and similar_stem.startswith(prefix):
                        similar_stem = similar_stem[len(prefix) :]
                    if suffix_old and similar_stem.endswith(suffix_old):
                        similar_stem = similar_stem[: -len(suffix_old)]

                    # Наш stem = наше слово минус суффикс минус префикс
                    our_stem = word
                    if prefix and our_stem.startswith(prefix):
                        our_stem = our_stem[len(prefix) :]
                    if suffix_old and our_stem.endswith(suffix_old):
                        our_stem = our_stem[: -len(suffix_old)]

                    # Получаем тег
                    pos, grammemes = self._dawg_dict.parse_tag_string(tag_string)

                    # Получаем нормальную форму
                    normal_form_info = self._dawg_dict.get_paradigm(paradigm_id, 0)
                    if normal_form_info:
                        normal_suffix, _, normal_prefix = normal_form_info
                        normal_form = normal_prefix + our_stem + normal_suffix
                    else:
                        normal_form = word

                    mawo_tag = MAWOTag(pos, grammemes)
                    mawo_parse = MAWOParse(
                        word=word,
                        normal_form=normal_form,
                        tag=mawo_tag,
                        score=0.5,  # Пониженный score для предсказанных
                        analyzer=self,
                        paradigm_id=paradigm_id,
                        stem=our_stem,
                    )
                    results.append(mawo_parse)
                    return results  # Возвращаем первый результат

        return results

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

    # ========== SPECIAL ANALYZERS HELPER METHODS ==========

    def _is_punctuation(self, word: str) -> bool:
        """Проверка является ли токен пунктуацией."""
        import string

        # Расширенная пунктуация (включая Unicode)
        punct_chars = set(string.punctuation + "…—–")
        return all(c in punct_chars for c in word) and len(word) > 0

    def _analyze_number(self, word: str) -> list[MAWOParse] | None:
        """Анализ числовых токенов."""
        import re

        # Integer: 123, 0
        if re.match(r"^\d+$", word):
            return [
                MAWOParse(
                    word=word,
                    normal_form=word,
                    tag=MAWOTag("NUMB", {"intg"}),
                    score=1.0,
                    analyzer=self,
                )
            ]

        # Real number: 123.1 or 123,1
        if re.match(r"^\d+[.,]\d+$", word):
            return [
                MAWOParse(
                    word=word,
                    normal_form=word,
                    tag=MAWOTag("NUMB", {"real"}),
                    score=1.0,
                    analyzer=self,
                )
            ]

        return None

    def _analyze_roman(self, word: str) -> list[MAWOParse] | None:
        """Анализ римских цифр."""
        import re

        # Римские цифры: I, V, X, L, C, D, M (case insensitive)
        if re.match(r"^[IVXLCDM]+$", word.upper()) and len(word) > 0:
            # Проверяем что это действительно похоже на римскую цифру
            # (не просто случайная комбинация букв)
            upper_word = word.upper()
            # Базовая проверка валидности римской цифры
            if self._is_valid_roman(upper_word):
                return [
                    MAWOParse(
                        word=word,
                        normal_form=word.lower(),
                        tag=MAWOTag("ROMN", set()),
                        score=1.0,
                        analyzer=self,
                    )
                ]

        return None

    def _is_valid_roman(self, word: str) -> bool:
        """Проверка валидности римской цифры."""
        # Простая эвристика: римские цифры обычно содержат I, V, X
        # и не содержат более 3 одинаковых символов подряд (кроме M)
        valid_chars = set("IVXLCDM")
        if not set(word).issubset(valid_chars):
            return False

        # Проверяем на повторы (не более 3-4 подряд)
        for char in "IVXLCD":
            if char * 4 in word:
                return False

        return True

    def _is_latin(self, word: str) -> bool:
        """Проверка является ли текст латинским (не кириллица)."""
        # Латинский текст - содержит хотя бы одну латинскую букву
        has_latin = any("a" <= c.lower() <= "z" for c in word)
        has_cyrillic = any("а" <= c.lower() <= "я" or c.lower() == "ё" for c in word)

        if "-" in word and has_latin and has_cyrillic:
            # Compound word с латиницей и кириллицей
            # Примеры:
            # - "Ретро-FM" → LATN (FM - неизменяемая аббревиатура)
            # - "pdf-документов" → NOUN (документов - склоняется)

            parts = word.split("-")
            latin_parts = []
            cyrillic_parts = []

            for part in parts:
                part_has_latin = any("a" <= c.lower() <= "z" for c in part)
                part_has_cyrillic = any("а" <= c.lower() <= "я" or c.lower() == "ё" for c in part)

                if part_has_latin:
                    latin_parts.append(part)
                if part_has_cyrillic:
                    cyrillic_parts.append(part)

            # Проверяем выглядит ли кириллическая часть как склоняемое слово
            # Если да → compound word → не LATN
            # Если нет → скорее LATN
            inflection_endings = ["ов", "ам", "ами", "ах", "ями", "ях", "ей", "ой", "ую", "ом"]
            for cyrillic_part in cyrillic_parts:
                for ending in inflection_endings:
                    if cyrillic_part.endswith(ending) and len(cyrillic_part) > len(ending) + 2:
                        # Кириллическая часть склоняется → compound word → не LATN
                        return False

            # Если кириллическая часть не склоняется и есть латиница → LATN
            return True
        else:
            # Обычное слово - латиница только если НЕТ кириллицы
            return has_latin and not has_cyrillic


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
