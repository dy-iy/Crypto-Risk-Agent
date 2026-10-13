"""Actionable task errors without credentials, upstream bodies, or server paths."""
import asyncio
import aiohttp
import httpx
from openai import APIError, APITimeoutError, APIConnectionError, APIStatusError


class ModelDeadlineError(TimeoutError):
    """The workflow's model wall-clock deadline expired."""


def failure_message(exc: Exception, stage: str) -> str:
    chain = []
    current = exc
    while current is not None and id(current) not in {id(item) for item in chain}:
        chain.append(current)
        current = current.__cause__
    model_error = next((item for item in chain if isinstance(item, APIError)), None)
    if any(isinstance(item, ModelDeadlineError) for item in chain):
        return f'{stage}失败（ModelDeadlineError）：DeepSeek 模型调用超过总时限，请稍后重试或缩小分析范围。'
    if model_error is not None:
        kind = type(model_error).__name__
        if isinstance(model_error, APITimeoutError):
            reason = 'DeepSeek 模型响应超时，有限重试后仍未完成，请稍后重试'
        elif isinstance(model_error, APIStatusError):
            reason = f'DeepSeek 返回 HTTP {model_error.status_code}，请检查模型服务授权、余额或配额'
        elif isinstance(model_error, APIConnectionError):
            reason = '无法连接 DeepSeek 模型服务，请检查网络与模型 API 地址'
        else:
            reason = 'DeepSeek 模型请求异常，请查看任务文件日志'
        return f'{stage}失败（{kind}）：{reason}。'
    exc = next((item for item in chain if isinstance(item, (TimeoutError, httpx.HTTPError, aiohttp.ClientError))), exc)
    kind = type(exc).__name__
    if isinstance(exc, (TimeoutError, asyncio.TimeoutError, httpx.TimeoutException)):
        reason = '外部数据服务连接或响应超时，请检查 RPC、区块浏览器与 Tenderly 的连通性后重试'
    elif isinstance(exc, (httpx.HTTPStatusError, aiohttp.ClientResponseError)):
        status = exc.response.status_code if isinstance(exc, httpx.HTTPStatusError) else exc.status
        reason = f'外部数据服务返回 HTTP {status}，请检查服务授权、配额与可用性'
    elif isinstance(exc, (httpx.RequestError, aiohttp.ClientError)):
        reason = '无法连接外部数据服务，请检查网络与服务配置后重试'
    else:
        reason = '执行异常，请查看任务文件日志定位具体原因'
    return f'{stage}失败（{kind}）：{reason}。'
