from decimal import Decimal


def format_rate_pct(rate: Decimal) -> str:
    """Formatuje stawkę podatkową jako procent, np. 12% lub 8,5%."""
    val = rate * Decimal("100")
    if val % 1 == 0:
        return f"{int(val)}%"
    return f"{val:.1f}%".replace(".", ",")
