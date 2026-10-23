"""Lossless sharing of repeated price evidence in analysis prompts."""
import ast
import json
import re


def compact_price_evidence(transfer_graph, balance_change):
    """Return prompt copies and a registry; leave all original evidence intact."""
    quotes = {}
    quote_ids = {}

    def reference(quote):
        # Every field participates in identity, including unavailable prices,
        # asset mappings, precision and chain/block provenance.
        key = json.dumps(quote, sort_keys=True, ensure_ascii=False)
        if key not in quote_ids:
            quote_ids[key] = f"price_evidence_{len(quotes) + 1}"
            quotes[quote_ids[key]] = quote
        return {"$ref": quote_ids[key]}

    def compact(value):
        if isinstance(value, dict):
            return {
                key: reference(item) if key == "price_evidence" and isinstance(item, dict)
                else compact(item)
                for key, item in value.items()
            }
        if isinstance(value, list):
            return [compact(item) for item in value]
        return value

    def graph_quote(match):
        try:
            quote = ast.literal_eval(match.group(1))
        except (ValueError, SyntaxError, RecursionError):
            return match.group(0)
        return f"price_evidence={reference(quote)}" if isinstance(quote, dict) else match.group(0)

    if isinstance(transfer_graph, str):
        # TGraph serializes one edge per line. Preserve unknown formats verbatim.
        transfer_graph = re.sub(
            r"price_evidence=(\{[^\n]*\})(?=, timestamp=)", graph_quote, transfer_graph,
        )
    else:
        transfer_graph = compact(transfer_graph)
    return transfer_graph, compact(balance_change), quotes
