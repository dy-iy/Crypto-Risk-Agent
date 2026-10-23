"""Actionable task errors without credentials, upstream bodies, or server paths."""
import asyncio
import aiohttp
import httpx
from openai import APIError, APITimeoutError, APIConnectionError, APIStatusError


class ModelDeadlineError(TimeoutError):
    """The workflow's model wall-clock deadline expired."""


class EvidencePersistenceError(OSError):
    """Required evidence could not be saved; never report an incomplete result."""


class AgentContractError(ValueError):
    """A bounded agent correction could not produce usable structured data."""

    def __init__(self, stage, reason_code):
        self.stage = stage if stage in {'classification', 'filter', 'task', 'trace', 'memory', 'report'} else 'agent'
        self.reason_code = reason_code if reason_code in {
            'agent_classification_invalid', 'agent_filter_invalid', 'agent_task_invalid',
            'agent_trace_arguments_invalid', 'agent_trace_evidence_invalid',
            'agent_hypothesis_invalid', 'agent_memory_invalid', 'agent_trace_tool_selection_missing',
            'analysis_report_invalid', 'agent_context_budget_exceeded',
        } else 'agent_output_invalid'
        message = ('模型两次未选择调试工具，无法继续执行轨迹分析。'
                   if self.reason_code == 'agent_trace_tool_selection_missing' else
                   '当前系统指令与完整输入证据超过模型上下文预算，请分批提供证据；未发送截断的证据。'
                   if self.reason_code == 'agent_context_budget_exceeded' else
                   f'智能体数据契约校验未通过 [{self.reason_code}]；未将缺失或非法输出当作成功或安全结论。')
        super().__init__(message)


class ChainRPCError(RuntimeError):
    """Safe RPC diagnostics: protocol fields, never URLs or provider messages."""

    def __init__(self, reason, *, method=None, status_code=None, rpc_code=None):
        reasons = {
            'timeout': 'RPC 请求超过时限', 'unavailable': '无法连接 RPC 服务',
            'http_error': 'RPC 服务返回异常 HTTP 状态',
            'invalid_response': 'RPC 响应格式或请求标识不匹配',
            'rpc_error': 'RPC 返回执行错误',
        }
        self.reason_code = reason if reason in reasons else 'invalid_response'
        self.method = method if isinstance(method, str) and method.replace('_', '').isalnum() and len(method) <= 80 else None
        self.status_code = status_code if type(status_code) is int and 100 <= status_code <= 599 else None
        self.rpc_code = rpc_code if type(rpc_code) is int and abs(rpc_code) <= 2 ** 31 else None
        self.retryable = (self.reason_code in {'timeout', 'unavailable'}
                          or self.status_code in {408, 429}
                          or self.status_code is not None and self.status_code >= 500
                          or self.rpc_code in {-32005, -32016, -32603})
        parts = [reasons[self.reason_code]]
        if self.method:
            parts.append(self.method)
        if self.status_code is not None:
            parts.append(f'HTTP {self.status_code}')
        if self.rpc_code is not None:
            parts.append(f'code={self.rpc_code}')
        super().__init__('；'.join(parts) + '。')


class HistoricalReplayContextError(ValueError):
    """The original transaction's execution position cannot be established."""


class HistoricalReplayValidationError(ValueError):
    """An original replay is unavailable or disagrees with its RPC receipt."""

    def __init__(self, status: str, reason_code: str, *, details=None):
        self.status = status if status in {'unavailable', 'inconsistent'} else 'unavailable'
        reasons = {
            'missing_evidence': '原始交易、回执或模拟结果缺少必要证据，无法完成一致性校验',
            'receipt_mismatch': 'RPC 交易与回执的身份、区块或事件记录不一致',
            'context_mismatch': '模拟的网络、历史执行位置或交易参数与原始交易不一致',
            'execution_mismatch': '模拟的执行状态或 Gas 用量与真实交易回执不一致',
            'event_mismatch': '模拟事件的数量、顺序或原始内容与真实交易回执不一致',
        }
        self.reason_code = reason_code if reason_code in reasons else 'missing_evidence'
        # Do not copy provider bodies, RPC URLs, credentials, or arbitrary values.
        field = details.get('field') if isinstance(details, dict) else None
        self.details = {'field': field} if isinstance(field, str) and all(
            char.isalnum() or char in '._' for char in field
        ) and len(field) <= 120 else {}
        self.message = reasons[self.reason_code]
        super().__init__(f'原始重放一致性校验未通过 [{self.reason_code}]：{self.message}；已停止后续分析。')


class TenderlyAPIError(RuntimeError):
    """Actionable upstream failure without a response body or credentials."""

    def __init__(self, operation: str, *, status_code=None, error_code=None,
                 retryable: bool = False, message: str | None = None):
        operations = {
            'simulate': '创建交易模拟',
            'simulation_result': '读取模拟结果',
            'simulate_bundle': '执行补丁回放',
        }
        self.operation = operation if operation in operations else 'request'
        self.status_code = status_code if type(status_code) is int and 100 <= status_code <= 599 else None
        auth_codes = {'unauthorized', 'unauthenticated', 'authentication_failed', 'invalid_access_key', 'invalid_api_key'}
        quota_codes = {'quota_exceeded', 'insufficient_quota', 'monthly_limit_exceeded', 'limit_exceeded', 'payment_required', 'simulation_limit_exceeded'}
        allowed_codes = auth_codes | quota_codes | {
            'insufficient_permissions', 'forbidden', 'resource_not_found', 'not_found',
            'simulation_not_found', 'project_not_found', 'too_many_requests', 'rate_limit_exceeded',
            'invalid_request', 'bad_request', 'invalid_response', 'internal_server_error',
            'service_unavailable', 'timeout', 'gateway_timeout',
        }
        self.error_code = error_code if isinstance(error_code, str) and error_code in allowed_codes else None
        self.retryable = bool(retryable)
        if self.error_code in auth_codes or self.status_code == 401:
            reason = '认证失败，请检查 Tenderly API 密钥是否有效'
            self.retryable = False
        elif self.error_code in quota_codes or self.status_code == 402:
            reason = '可用额度不足或已达到使用上限，请检查 Tenderly 后台用量与套餐'
            self.retryable = False
        elif self.error_code in {'insufficient_permissions', 'forbidden'} or self.status_code == 403:
            reason = '访问权限不足，请检查 Tenderly 账号、项目和 API 密钥的授权范围'
            self.retryable = False
        elif self.error_code in {'resource_not_found', 'not_found', 'simulation_not_found', 'project_not_found'} or self.status_code == 404:
            reason = '项目或模拟记录不存在，请检查 Tenderly 项目配置或重新获取模拟记录'
            self.retryable = False
        elif self.error_code in {'too_many_requests', 'rate_limit_exceeded'} or self.status_code == 429:
            reason = '请求受到限流，有限重试后仍未完成，请稍后重试'
        elif self.error_code in {'invalid_request', 'bad_request'} or self.status_code in {400, 422}:
            reason = '请求参数未通过校验，请检查历史区块、交易序号和交易字段'
            self.retryable = False
        elif self.error_code in {'timeout', 'gateway_timeout'} or self.status_code == 408:
            reason = '连接或响应超时，有限重试后仍未完成，请检查网络或稍后重试'
        elif self.error_code in {'internal_server_error', 'service_unavailable'} or (self.status_code is not None and self.status_code >= 500):
            reason = '服务暂时异常，有限重试后仍未恢复，请稍后重试'
        elif self.error_code == 'invalid_response':
            reason = '响应格式无效或缺少必要的模拟数据，请稍后重试'
        else:
            reason = '请求失败，请检查 Tenderly 服务状态与项目配置'
        # Callers may provide fixed diagnostic detail, but upstream text is never
        # included in the exception shown to users or persisted in task logs.
        self.message = reason
        operation_label = operations.get(self.operation, '请求')
        status_label = f'（HTTP {self.status_code}）' if self.status_code is not None else ''
        code_label = f' [{self.error_code}]' if self.error_code else ''
        super().__init__(f'Tenderly {operation_label}{status_label}{code_label}：{reason}。')


def exception_chain(exc: BaseException) -> list[BaseException]:
    """Find typed causes even through implicit wrappers or SDK task groups."""
    chain, pending, seen = [], [exc], set()
    while pending and len(chain) < 32:
        current = pending.pop(0)
        if id(current) in seen:
            continue
        seen.add(id(current))
        chain.append(current)
        if current.__cause__ is not None:
            pending.append(current.__cause__)
        elif not current.__suppress_context__ and current.__context__ is not None:
            pending.append(current.__context__)
        if isinstance(current, BaseExceptionGroup):
            pending.extend(current.exceptions)
    return chain


def failure_message(exc: Exception, stage: str) -> str:
    from app.attackpilot.mcp_tools.mcp_client import MCPToolError
    chain = exception_chain(exc)
    agent_error = next((item for item in chain if isinstance(item, AgentContractError)), None)
    if agent_error is not None:
        return f'{stage}失败（AgentContractError）：{agent_error}'
    if any(isinstance(item, EvidencePersistenceError) for item in chain):
        return f'{stage}失败（EvidencePersistenceError）：必要的分析证据未能完整保存，请检查任务存储空间与写入权限后重试。'
    mcp_error = next((item for item in chain if isinstance(item, MCPToolError)), None)
    if mcp_error is not None:
        return f'{stage}失败（MCPToolError）：分析工具调用失败 [{mcp_error.reason_code}]；未将错误响应作为有效证据继续分析。'
    rpc_error = next((item for item in chain if isinstance(item, ChainRPCError)), None)
    if rpc_error is not None:
        return f'{stage}失败（ChainRPCError）：{rpc_error}'
    replay_error = next((item for item in chain if isinstance(item, HistoricalReplayValidationError)), None)
    if replay_error is not None:
        return f'{stage}失败（HistoricalReplayValidationError）：{replay_error}'
    if any(isinstance(item, HistoricalReplayContextError) for item in chain):
        return f'{stage}失败（HistoricalReplayContextError）：无法确定原交易的区块号或交易序号，请检查 RPC 返回的历史交易数据；未使用默认位置进行重放。'
    tenderly_error = next((item for item in chain if isinstance(item, TenderlyAPIError)), None)
    if tenderly_error is not None:
        return f'{stage}失败（TenderlyAPIError）：{tenderly_error}'
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
