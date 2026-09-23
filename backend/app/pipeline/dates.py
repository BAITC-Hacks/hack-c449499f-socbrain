"""Перевод сроков из речи ("до пятницы", "к пятнадцатому октября", "жұмаға дейін") в даты.

Правила детерминированные: LLM только цитирует срок, а дату считаем здесь —
так результат воспроизводим и не зависит от галлюцинаций модели.
"""
import calendar
import re
from datetime import date, timedelta

MONTHS = [
    # (префикс, номер месяца) — русские и казахские формы
    ("январ", 1), ("феврал", 2), ("март", 3), ("апрел", 4), ("мая", 5), ("май", 5), ("мае", 5),
    ("июн", 6), ("июл", 7), ("август", 8), ("сентябр", 9), ("октябр", 10), ("ноябр", 11), ("декабр", 12),
    ("қаңтар", 1), ("ақпан", 2), ("наурыз", 3), ("сәуір", 4), ("мамыр", 5), ("маусым", 6),
    ("шілде", 7), ("тамыз", 8), ("қыркүйек", 9), ("қазан", 10), ("қараша", 11), ("желтоқсан", 12),
]

WEEKDAYS = [
    (r"понедельник", 0), (r"вторник", 1), (r"сред[аыуе]\b", 2), (r"четверг", 3), (r"пятниц", 4),
    (r"суббот", 5), (r"воскресень", 6),
    (r"дүйсенбі", 0), (r"сейсенбі", 1), (r"сәрсенбі", 2), (r"бейсенбі", 3), (r"жұма", 4),
    (r"(?<![а-яәғқңөұүһі])сенбі", 5), (r"жексенбі", 6),
]

ORDINAL_STEMS = sorted([
    ("перв", 1), ("втор", 2), ("трет", 3), ("четвёрт", 4), ("четверт", 4), ("пят", 5), ("шест", 6),
    ("седьм", 7), ("восьм", 8), ("девят", 9), ("десят", 10), ("одиннадцат", 11), ("двенадцат", 12),
    ("тринадцат", 13), ("четырнадцат", 14), ("пятнадцат", 15), ("шестнадцат", 16), ("семнадцат", 17),
    ("восемнадцат", 18), ("девятнадцат", 19), ("двадцат", 20), ("тридцат", 30),
], key=lambda item: -len(item[0]))
ORDINAL_ENDINGS = ("ого", "ому", "ое", "ый", "ой", "ым", "ом", "ье", "ьего", "ьему", "ий", "ая", "ую", "ее", "его", "ему")
TENS = {"двадцать": 20, "тридцать": 30}

NUMBERS = {
    "один": 1, "одну": 1, "одна": 1, "одного": 1, "два": 2, "две": 2, "двух": 2, "три": 3, "трёх": 3,
    "трех": 3, "четыре": 4, "пять": 5, "шесть": 6, "семь": 7, "восемь": 8, "девять": 9, "десять": 10,
    "бір": 1, "екі": 2, "үш": 3, "төрт": 4, "бес": 5, "алты": 6, "жеті": 7, "сегіз": 8, "тоғыз": 9, "он": 10,
}

WORD = r"[0-9a-zа-яёәғқңөұүһі]+"


def _month(token: str) -> int | None:
    for prefix, month in MONTHS:
        if token.startswith(prefix):
            return month
    return None


def _ordinal(token: str) -> int | None:
    if token.isdigit():
        return int(token)
    if not token.endswith(ORDINAL_ENDINGS):
        return None
    for stem, value in ORDINAL_STEMS:
        if token.startswith(stem):
            return value
    return None


def _number(token: str) -> int | None:
    if token.isdigit():
        return int(token)
    return NUMBERS.get(token)


def _with_year(day: int, month: int, base: date) -> date | None:
    try:
        candidate = date(base.year, month, day)
    except ValueError:
        return None
    # "до 15 января", сказанное в декабре, — это уже следующий год
    if candidate < base - timedelta(days=31):
        candidate = date(base.year + 1, month, day)
    return candidate


def _next_weekday(base: date, weekday: int) -> date:
    ahead = (weekday - base.weekday()) % 7
    return base + timedelta(days=ahead or 7)


def _week_friday(base: date, weeks: int = 0) -> date:
    friday = base + timedelta(days=4 - base.weekday()) + timedelta(weeks=weeks)
    return max(friday, base)


def _add_business_days(base: date, days: int) -> date:
    current = base
    while days > 0:
        current += timedelta(days=1)
        if current.weekday() < 5:
            days -= 1
    return current


def _add_months(base: date, months: int) -> date:
    month_index = base.month - 1 + months
    year, month = base.year + month_index // 12, month_index % 12 + 1
    return date(year, month, min(base.day, calendar.monthrange(year, month)[1]))


def parse_deadline(text: str | None, base: date) -> date | None:
    """Возвращает дату срока относительно даты совещания или None, если срок не распознан."""
    if not text:
        return None
    lowered = text.lower()
    tokens = re.findall(WORD, lowered)

    # 1. Явная дата: "15.10", "15.10.2026"
    numeric = re.search(r"\b(\d{1,2})\.(\d{1,2})(?:\.(\d{2,4}))?\b", lowered)
    if numeric:
        day, month = int(numeric.group(1)), int(numeric.group(2))
        if numeric.group(3):
            year = int(numeric.group(3))
            year = year + 2000 if year < 100 else year
            try:
                return date(year, month, day)
            except ValueError:
                return None
        return _with_year(day, month, base)

    # 2. "15 октября", "к пятнадцатому октября", "до двадцать пятого сентября", "15 қазан"
    for i, token in enumerate(tokens):
        month = _month(token)
        if month and i > 0:
            day = _ordinal(tokens[i - 1])
            if day is not None and i > 1 and tokens[i - 2] in TENS and day < 10:
                day += TENS[tokens[i - 2]]
            if day and 1 <= day <= 31:
                return _with_year(day, month, base)

    # 3. Конец периода
    if re.search(r"конц\w* квартал", lowered):
        quarter_end_month = ((base.month - 1) // 3 + 1) * 3
        return date(base.year, quarter_end_month, calendar.monthrange(base.year, quarter_end_month)[1])
    if re.search(r"конц\w* месяц|ай соңына", lowered):
        return date(base.year, base.month, calendar.monthrange(base.year, base.month)[1])
    if re.search(r"конц\w* год", lowered):
        return date(base.year, 12, 31)

    # 4. Неделя: "на этой неделе", "до конца недели", "на следующей неделе"
    if re.search(r"следующ\w*\s+недел|келесі\s+апта", lowered):
        return _week_friday(base, weeks=1)
    if re.search(r"(эт|текущ)\w*\s+недел|конц\w*\s+недел|осы\s+апта", lowered):
        return _week_friday(base)

    # 5. Относительные периоды: "за две недели", "5 рабочих дней", "екі апта"
    period = re.search(
        rf"(?:\b({WORD})\s+)?(рабоч\w+\s+)?\b(день|дня|дней|недел\w*|месяц\w*|күн\w*|апта\w*|ай)\b", lowered
    )
    if period:
        amount = _number(period.group(1) or "") or 1
        unit = period.group(3)
        if unit.startswith(("недел", "апта")):
            return base + timedelta(weeks=amount)
        if unit.startswith(("месяц", "ай")):
            return _add_months(base, amount)
        if period.group(2):
            return _add_business_days(base, amount)
        return base + timedelta(days=amount)

    # 6. День недели: "до пятницы", "к среде", "жұмаға дейін"
    for pattern, weekday in WEEKDAYS:
        if re.search(pattern, lowered):
            return _next_weekday(base, weekday)

    # 7. Завтра / послезавтра
    if "послезавтра" in lowered or "бүрсігүні" in lowered:
        return base + timedelta(days=2)
    if "завтра" in lowered or "ертең" in lowered:
        return base + timedelta(days=1)
    if "сегодня" in lowered or "бүгін" in lowered:
        return base

    return None
