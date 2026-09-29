from datetime import date

from sprint_radar.workdays import br_holidays, business_days, easter


def test_easter_known_years():
    assert easter(2026) == date(2026, 4, 5)
    assert easter(2027) == date(2027, 3, 28)


def test_moveable_holidays_2026():
    h = br_holidays(2026)
    assert date(2026, 2, 16) in h  # Carnaval
    assert date(2026, 2, 17) in h
    assert date(2026, 4, 3) in h  # Paixão
    assert date(2026, 6, 4) in h  # Corpus Christi


def test_sprint06_has_ten_business_days():
    assert len(business_days(date(2026, 9, 21), date(2026, 10, 2))) == 10


def test_holiday_and_weekend_excluded():
    days = business_days(date(2026, 9, 4), date(2026, 9, 8))
    assert days == [date(2026, 9, 4), date(2026, 9, 8)]  # 5-6 fim de semana, 7 feriado


def test_empty_when_end_before_start():
    assert business_days(date(2026, 10, 2), date(2026, 9, 21)) == []
