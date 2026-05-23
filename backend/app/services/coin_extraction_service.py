import re
from typing import TypedDict


class CoinMatch(TypedDict):
    symbol: str
    name: str
    matched_terms: list[str]


COIN_DICTIONARY: dict[str, dict[str, list[str] | str]] = {
    "BTC": {"name": "Bitcoin", "terms": ["BTC", "Bitcoin", "比特币"]},
    "ETH": {"name": "Ethereum", "terms": ["ETH", "Ethereum", "以太坊"]},
    "SOL": {"name": "Solana", "terms": ["SOL", "Solana"]},
    "BNB": {"name": "BNB", "terms": ["BNB", "Binance Coin", "币安币"]},
    "XRP": {"name": "XRP", "terms": ["XRP", "Ripple", "瑞波"]},
    "DOGE": {"name": "Dogecoin", "terms": ["DOGE", "Dogecoin", "狗狗币"]},
    "ADA": {"name": "Cardano", "terms": ["ADA", "Cardano"]},
    "TRX": {"name": "Tron", "terms": ["TRX", "Tron", "波场"]},
    "USDT": {"name": "Tether", "terms": ["USDT", "Tether", "泰达币"]},
    "USDC": {"name": "Circle USD", "terms": ["USDC", "Circle USD", "USD Coin"]},
    "TON": {"name": "Toncoin", "terms": ["TON", "Toncoin"]},
    "AVAX": {"name": "Avalanche", "terms": ["AVAX", "Avalanche"]},
    "LINK": {"name": "Chainlink", "terms": ["LINK", "Chainlink"]},
    "MATIC": {"name": "Polygon", "terms": ["MATIC", "Polygon"]},
    "POL": {"name": "Polygon Ecosystem Token", "terms": ["POL"]},
    "DOT": {"name": "Polkadot", "terms": ["DOT", "Polkadot"]},
    "LTC": {"name": "Litecoin", "terms": ["LTC", "Litecoin", "莱特币"]},
    "BCH": {"name": "Bitcoin Cash", "terms": ["BCH", "Bitcoin Cash"]},
    "SHIB": {"name": "Shiba Inu", "terms": ["SHIB", "Shiba Inu"]},
    "PEPE": {"name": "Pepe", "terms": ["PEPE", "Pepe"]},
    "AAVE": {"name": "Aave", "terms": ["AAVE", "Aave"]},
    "UNI": {"name": "Uniswap", "terms": ["UNI", "Uniswap"]},
    "CRV": {"name": "Curve", "terms": ["CRV", "Curve"]},
    "OP": {"name": "Optimism", "terms": ["OP", "Optimism"]},
    "ARB": {"name": "Arbitrum", "terms": ["ARB", "Arbitrum"]},
    "SUI": {"name": "Sui", "terms": ["SUI"]},
    "SEI": {"name": "Sei", "terms": ["SEI"]},
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
