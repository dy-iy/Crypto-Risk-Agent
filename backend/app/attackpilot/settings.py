"""AttackPilot resources and configuration; credentials live only in .env."""
import json
import os
import re
from pathlib import Path

from dotenv import load_dotenv
from app.services.llm_config_service import get_deepseek_config

PACKAGE_ROOT = Path(__file__).resolve().parent
BACKEND_ROOT = PACKAGE_ROOT.parents[1]
for env_file in (BACKEND_ROOT.parent / ".env", BACKEND_ROOT / ".env"):
    load_dotenv(env_file)

PROJECT_PATH = str(PACKAGE_ROOT)
RUNTIME_ROOT = Path(os.getenv("ATTACKPILOT_RUNTIME_DIR", str(BACKEND_ROOT / "runtime/attackpilot"))).resolve()
WORK_ROOT = Path(os.getenv("ATTACKPILOT_WORK_DIR", str(RUNTIME_ROOT / "shared"))).resolve()
DATABASE_PATH = Path(os.getenv("ATTACKPILOT_DB_PATH", str(RUNTIME_ROOT / "attackpilot.sqlite3"))).resolve()
COMPILER_ROOT = RUNTIME_ROOT / "compiler"
RAW_JSON_PATH = str(PACKAGE_ROOT / "dataset/raw")
PROMPT_PATH = str(PACKAGE_ROOT / "prompt")
CACHE_DIR = str(WORK_ROOT / "cache")
TMP_FILE_DIR = str(WORK_ROOT / "tmp")
MANIPULATE_PATH = str(WORK_ROOT / "local_manipulate")
NODE_PATH = os.getenv("ATTACKPILOT_NODE_PATH", "node")
SIGNATURE_PATH = str(PACKAGE_ROOT / "misc/SignItem.csv")
MCP_SERVER_PATH = str(PACKAGE_ROOT / "mcp_tools/mcp_server.py")

def _resource(name: str) -> str:
    return (PACKAGE_ROOT / "misc" / name).read_text(encoding="utf-8")

PC_TRACER = re.sub(r"\n|\t", "", _resource("tracer.js")[9:])
PHALCON_TRACER = _resource("phalcon_tracer.js")
TYPED_AST_CODE = _resource("ast.js")
SOLCJS_CODE = _resource("solcjs.js")

def _mapping(key: str) -> dict[str, list[str]]:
    try:
        value = json.loads(os.getenv(key, "{}"))
        return {chain: [str(url) for url in urls if url] for chain, urls in value.items() if isinstance(urls, list)}
    except (ValueError, AttributeError, TypeError):
        return {}

JSONRPCS = _mapping("ATTACKPILOT_RPC_URLS")
SCAN_APIKEYS = _mapping("ATTACKPILOT_SCAN_URLS")
WEB3_PROVIDER = os.getenv("ATTACKPILOT_WEB3_PROVIDER", "")
TENDERLY_API_KEY = os.getenv("ATTACKPILOT_TENDERLY_API_KEY", "")
ACCOUNT_SLUG = os.getenv("ATTACKPILOT_TENDERLY_ACCOUNT", "")
PROJECT_SLUG = os.getenv("ATTACKPILOT_TENDERLY_PROJECT", "")
LLM_NAME = "deepseek-flash"
LLM_API_KEY = os.getenv("DEEPSEEK_API_KEY", "")
LLM_BASE_URL = get_deepseek_config().base_url
LLM_MAX_CONCURRENT = 5
INIT_DEPTH = 2
TOTAL_TURN = 3
GUIDE_TURN = 15
TX_DEBUG_TURN = 80
TX_DEBUG_MAX_IDLE_TURNS = 40
PATCH_TURN = 3
FIX_TURN = 15
PATCH_FILE = "test/PatchVerification.t.sol"
ATTACK_DATA_FILE = "test/data/attack_data.json"
TRANSACTION_FILTER_SMALL_SET_THRESHOLD = 1
PLATFORM_TO_CHAIN_ID = {"Ethereum": 1, "BNBChain": 56, "BSC": 56, "Arbitrum": 42161, "Polygon": 137, "Optimism": 10, "Avalanche": 43114, "Fantom": 250, "Base": 8453}

def prepare_work_dir() -> None:
    for path in (WORK_ROOT, Path(CACHE_DIR), Path(TMP_FILE_DIR)):
        path.mkdir(parents=True, exist_ok=True)

def node_environment() -> dict[str, str]:
    # Generated scripts live under a task's temporary directory, outside node_modules.
    return {**os.environ, "NODE_PATH": str(PACKAGE_ROOT / "node_modules")}
