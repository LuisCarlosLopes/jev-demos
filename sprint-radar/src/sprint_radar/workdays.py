"""Dias úteis com feriados nacionais brasileiros. Toda aritmética de calendário vive aqui."""

from datetime import date, timedelta


def easter(year: int) -> date:
    """Domingo de Páscoa (algoritmo gregoriano anônimo)."""
    a = year % 19
    b, c = divmod(year, 100)
    d, e = divmod(b, 4)
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    m = (32 + 2 * e + 2 * i - h - k) % 7
    n = (a + 11 * h + 22 * m) // 451
    month, day = divmod(h + m - 7 * n + 114, 31)
    return date(year, month, day + 1)


def br_holidays(year: int) -> set[date]:
    pascoa = easter(year)
    return {
        date(year, 1, 1),
        date(year, 4, 21),
        date(year, 5, 1),
        date(year, 9, 7),
        date(year, 10, 12),
        date(year, 11, 2),
        date(year, 11, 15),
        date(year, 11, 20),
        date(year, 12, 25),
        pascoa - timedelta(days=48),  # segunda de Carnaval
        pascoa - timedelta(days=47),  # terça de Carnaval
        pascoa - timedelta(days=2),  # Sexta-feira da Paixão
        pascoa + timedelta(days=60),  # Corpus Christi
    }


def business_days(start: date, end: date) -> list[date]:
    """Dias úteis de segunda a sexta entre start e end, inclusive, sem feriados nacionais."""
    if end < start:
        return []
    holidays = set()
    for year in range(start.year, end.year + 1):
        holidays |= br_holidays(year)
    days = []
    current = start
    while current <= end:
        if current.weekday() < 5 and current not in holidays:
            days.append(current)
        current += timedelta(days=1)
    return days
