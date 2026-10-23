import asyncio
import time
import math


class AsyncItemBucket:
    def __init__(self, items: list, qps: int):
        if not isinstance(items, (list, tuple)):
            raise ValueError('数据服务配置必须为列表。')
        if isinstance(qps, bool) or not isinstance(qps, (int, float)) or not math.isfinite(qps) or qps <= 0:
            raise ValueError('数据服务请求频率必须为有限正数。')
        self.items = list(items)
        self.qps = qps

        self._last_get_time = [float('-inf') for _ in self.items]
        self._get_interval = 1 / qps
        self._lock = asyncio.Lock()

    async def get(self):
        if not self.items:
            raise ValueError('未配置可用的数据服务，请检查 RPC 或区块浏览器配置。')
        # Cancellation during rate-limit sleep must release the shared lock.
        async with self._lock:
            idx = min(range(len(self.items)), key=self._last_get_time.__getitem__)
            delay = self._get_interval - (time.monotonic() - self._last_get_time[idx])
            if delay > 0:
                await asyncio.sleep(delay)
            self._last_get_time[idx] = time.monotonic()
            return self.items[idx]


async def test(b):
    print(await b.get())


