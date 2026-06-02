import re
from typing import TypedDict

from app.services.coin_library_service import COIN_LIBRARY


class CoinMatch(TypedDict):
    symbol: str
    name: str
    matched_terms: list[str]


_EXTRA_TERMS: dict[str, list[str]] = {
    "BTC": ["比特币"],
    "ETH": ["以太坊"],
    "BNB": ["币安币"],
    "XRP": ["瑞波"],
    "DOGE": ["狗狗币"],
    "TRX": ["波场"],
    "USDT": ["泰达币"],
}

COIN_DICTIONARY: dict[str, dict[str, list[str] | str]] = {}
for coin in COIN_LIBRARY:
    base_asset = str(coin.get("base_asset") or "")
    if not base_asset:
        continue
    terms = [
        base_asset,
        str(coin.get("symbol") or ""),
        str(coin.get("name") or ""),
        *[str(alias) for alias in coin.get("aliases", [])],
        *_EXTRA_TERMS.get(base_asset, []),
    ]
    COIN_DICTIONARY[base_asset] = {
        "name": str(coin.get("name") or base_asset),
        "terms": list(dict.fromkeys(term for term in terms if term)),
    }


def _term_matches(text: str, term: str) -> bool:
    if not term:
        return False

    if re.search(r"[\u4e00-\u9fff]", term):
        return term in text

    pattern = rf"(?<![A-Za-z0-9]){re.escape(term)}(?![A-Za-z0-9])"
    return re.search(pattern, text, flags=re.IGNORECASE) is not None


def extract_coins_from_text(title: str, content: str) -> list[CoinMatch]:
    text = f"{title or ''}\n{content or ''}"
    matches: list[CoinMatch] = []

    for symbol, meta in COIN_DICTIONARY.items():
        terms = [str(term) for term in meta["terms"]]
        matched_terms = [term for term in terms if _term_matches(text, term)]
        if matched_terms:
            matches.append(
                {
                    "symbol": symbol,
                    "name": str(meta["name"]),
                    "matched_terms": matched_terms,
                }
            )

    return matches
