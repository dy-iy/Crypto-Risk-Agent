"""Trace selector labels and hexadecimal conversion."""
import re
from typing import Dict

COMMON_SELECTORS: Dict[str, str] = {
    # --- ERC20 / ERC721 Standard ---
    "a9059cbb": "transfer(address,uint256)",
    "23b872dd": "transferFrom(address,address,uint256)",
    "095ea7b3": "approve(address,uint256)",
    "70a08231": "balanceOf(address)",
    "18160ddd": "totalSupply()",
    "dd62ed3e": "allowance(address,address)",
    "42842e0e": "safeTransferFrom(address,address,uint256)",
    "b88d4fde": "safeTransferFrom(address,address,uint256,bytes)",
    "a22cb465": "setApprovalForAll(address,bool)",

    # --- Metadata ---
    "06fdde03": "name()",
    "95d89b41": "symbol()",
    "313ce567": "decimals()",
    "c87b56dd": "tokenURI(uint256)",

    # --- WETH / Native Wrap ---
    "d0e30db0": "deposit()",
    "2e1a7d4d": "withdraw(uint256)",

    # --- Uniswap V2 / V3 / Swap ---
    "0902f1ac": "getReserves()",
    "fff6cae9": "notifyRewardAmount(uint256)",
    "68b56f91": "swap(uint256,uint256,address,bytes)",  # Uniswap V2 pair swap
    "5909c0d5": "swap(address,bool,int256,uint160,bytes)",  # Uniswap V3 swap
    "38ed1739": "swapExactTokensForTokens(uint256,uint256,address[],address,uint256)",
    "18cbafe5": "swapExactTokensForETH(uint256,uint256,address[],address,uint256)",
    "7ff36ab5": "swapExactETHForTokens(uint256,address[],address,uint256)",

    # --- Proxy / Implementation ---
    "5c60da1b": "implementation()",
    "3659cfe6": "upgradeTo(address)",
    "4f1ef286": "upgradeToAndCall(address,bytes)",

    # --- Common Ownership ---
    "8da5cb5b": "owner()",
    "f2fde38b": "transferOwnership(address)",
    "715018a6": "renounceOwnership()",

    # --- Initialization ---
    "8129fc1c": "initialize()",
    "c4d66de8": "initialize(address)",
}


def hex_to_int(hex_str):
    if not hex_str or hex_str == '0x':
        return 0
    return int(hex_str, 16)


def parse_quantity(value):
    """Parse an unsigned chain quantity without guessing a string's radix."""
    if type(value) is int and value >= 0:
        return value
    if isinstance(value, str) and re.fullmatch(r'0x[0-9a-fA-F]+|[0-9]+', value):
        return int(value, 16 if value.startswith('0x') else 10)
    raise ValueError('Invalid unsigned chain quantity')
