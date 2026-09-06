"""
进程级共享 HTTP 客户端。

为什么用模块级单例 Session：requests.Session 的价值在 TCP/TLS 连接复用——
同一台服务器的连接放进底层连接池，后续请求免握手直接发送。
此前 SendRequest 每个请求新建一个局部 Session 用完即弃，复用率为零。

所有发 HTTP 请求的代码（框架执行器、auth 登录、pytest 原生用例）都应从本模块
取 SESSION，使整个测试进程共享同一个连接池。

注意：requests.Session 不会自动给请求加超时（这是 requests 的设计而非疏漏），
超时必须逐请求显式传递，统一使用本模块暴露的 HTTP_TIMEOUT。
"""
import requests
import urllib3
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from conf.operationConfig import OperationConfig


def _int_option(name, default):
    """读取 [HTTP] 段的整型配置项，缺失或非法时用默认值兜底。"""
    raw = OperationConfig().get_section_http(name)
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return default
    return value if value > 0 else default


HTTP_TIMEOUT = _int_option('timeout', 10)
_MAX_RETRIES = _int_option('max_retries', 3)
_POOL_MAXSIZE = _int_option('pool_maxsize', 20)
_verify_raw = OperationConfig().get_section_http('verify_ssl').strip().lower()
_VERIFY_SSL = _verify_raw not in ('false', '0', 'no', '')

# pytest.ini 的 filterwarnings=error 会把 InsecureRequestWarning 升级为异常导致请求直接失败，
# 在此统一压制一次（verify_ssl=false 仅应存在于本地 mock / 测试环境配置）。
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


def _build_session():
    """构建带连接池与失败重试策略的 Session。"""
    session = requests.Session()
    # 连接类重试（connect）：请求尚未发出即失败（DNS/TCP/TLS 握手阶段），对所有方法重试都安全；
    # 读超时重试关闭（read=0）：请求可能已到达服务端，重试有重复提交风险；
    # 状态码重试仅限网关类错误（502/503/504），且 urllib3 默认只重试幂等方法，
    # 避免"提交订单"这类非幂等请求在服务端已受理时被重复提交。
    retry = Retry(total=_MAX_RETRIES, connect=_MAX_RETRIES, read=0, status=2,
                  status_forcelist=(502, 503, 504), backoff_factor=0.3)
    adapter = HTTPAdapter(pool_connections=10, pool_maxsize=_POOL_MAXSIZE, max_retries=retry)
    session.mount('http://', adapter)
    session.mount('https://', adapter)
    session.verify = _VERIFY_SSL
    return session


SESSION = _build_session()
