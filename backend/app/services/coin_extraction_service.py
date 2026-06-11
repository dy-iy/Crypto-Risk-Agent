from functools import lru_cache
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

CoinTermEntry = tuple[str, str, str]


def _build_term_indexes() -> tuple[re.Pattern[str] | None, dict[str, list[CoinTermEntry]], tuple[CoinTermEntry, ...]]:
    non_cjk_lookup: dict[str, list[CoinTermEntry]] = {}
    non_cjk_terms: list[str] = []
    cjk_terms: list[CoinTermEntry] = []

    for symbol, meta in COIN_DICTIONARY.items():
        for term in [str(term) for term in meta["terms"]]:
            if re.search(r"[\u4e00-\u9fff]", term):
                cjk_terms.append((symbol, str(meta["name"]), term))
            else:
                key = term.casefold()
                non_cjk_lookup.setdefault(key, []).append((symbol, str(meta["name"]), term))
                non_cjk_terms.append(term)

    if not non_cjk_terms:
        return None, non_cjk_lookup, tuple(cjk_terms)

    alternatives = sorted((re.escape(term) for term in set(non_cjk_terms)), key=len, reverse=True)
    pattern = re.compile(rf"(?<![A-Za-z0-9])(?:{'|'.join(alternatives)})(?![A-Za-z0-9])", flags=re.IGNORECASE)
    return pattern, non_cjk_lookup, tuple(cjk_terms)


NON_CJK_TERM_PATTERN, NON_CJK_TERM_LOOKUP, CJK_TERMS = _build_term_indexes()


def _term_matches(text: str, term: str) -> bool:
    if not term:
        return False

    if re.search(r"[\u4e00-\u9fff]", term):
        return term in text

    pattern = rf"(?<![A-Za-z0-9]){re.escape(term)}(?![A-Za-z0-9])"
    return re.search(pattern, text, flags=re.IGNORECASE) is not None


@lru_cache(maxsize=8192)
def _extract_coin_tuples(title: str, content: str) -> tuple[tuple[str, str, tuple[str, ...]], ...]:
    text = f"{title or ''}\n{content or ''}"
    matched: dict[str, tuple[str, set[str]]] = {}

    if NON_CJK_TERM_PATTERN is not None:
        for match in NON_CJK_TERM_PATTERN.finditer(text):
            for symbol, name, term in NON_CJK_TERM_LOOKUP.get(match.group(0).casefold(), []):
                entry = matched.setdefault(symbol, (name, set()))
                entry[1].add(term)

    for symbol, name, term in CJK_TERMS:
        if term in text:
            entry = matched.setdefault(symbol, (name, set()))
            entry[1].add(term)

    return tuple(
        (symbol, name, tuple(sorted(terms)))
        for symbol, (name, terms) in matched.items()
    )


def extract_coins_from_text(title: str, content: str) -> list[CoinMatch]:
    return [
        {
            "symbol": symbol,
            "name": name,
            "matched_terms": list(matched_terms),
        }
        for symbol, name, matched_terms in _extract_coin_tuples(str(title or ""), str(content or ""))
    ]
