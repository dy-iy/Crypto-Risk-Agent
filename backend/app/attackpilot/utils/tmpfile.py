import os
import tempfile

from app.attackpilot.settings import TMP_FILE_DIR


async def wrap_run4tmpfile(data: str, async_func):
    os.makedirs(TMP_FILE_DIR, exist_ok=True)
    fd, path = tempfile.mkstemp(dir=TMP_FILE_DIR)
    path = path.replace('\\', '/')
    with os.fdopen(fd, 'w', encoding='utf-8') as f:
        f.write(data)
    try:
        return await async_func(path)
    finally:
        try:
            os.remove(path)
        except FileNotFoundError:
            pass
