from __future__ import annotations

import sys
from pathlib import Path

backend_root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(backend_root))
sys.path.insert(0, str(backend_root / 'app'))

from services.rag_service import get_rag_service


def main() -> None:
    status = get_rag_service().rebuild()
    print(status)


if __name__ == "__main__":
    main()
