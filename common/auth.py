"""
进程级登录态管理中心。

token、过期时间、Cookie 全部保存在内存中，由请求层（sendrequest）统一注入，
不再落盘。业务数据（订单号、商品ID等）由 common/context.py 的内存上下文传递。

复用 data/loginName.yaml 的账号数据与 conf/config.ini 的 [api_envi]/[TOKEN] 配置，
保证登录入口唯一：conftest 的 session 登录和 token 过期自动刷新都走 auth.login()。
"""
import threading
import time

import allure
import jsonpath
import requests
import urllib3

from conf.operationConfig import OperationConfig
from common.recordlog import logs
from common.readyaml import get_testcase_yaml

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


class AuthState:
    """登录态容器。线程锁保护登录/刷新动作，防止并发时重复登录。"""

    def __init__(self):
        self.token = None
        self.token_expire_time = 0
        self.cookies = {}
        self.refreshing = False
        self._lock = threading.Lock()
        self.conf = OperationConfig()
        # 加载 [TOKEN] 配置段（与原 sendrequest 逻辑一致）
        expire = self.conf.get_section_for_data('TOKEN', 'expire_seconds')
        self.token_expire_seconds = int(expire) if expire and expire.isdigit() else 3600
        advance = self.conf.get_section_for_data('TOKEN', 'refresh_advance_seconds')
        self.refresh_advance_seconds = int(advance) if advance and advance.isdigit() else 300
        codes = self.conf.get_section_for_data('TOKEN', 'invalid_status_codes')
        self.invalid_status_codes = [int(c) for c in (codes or '401,403').split(',') if c.strip().isdigit()]
        e_codes = self.conf.get_section_for_data('TOKEN', 'invalid_error_codes')
        self.invalid_error_codes = {c.strip() for c in (e_codes or '401,403').split(',') if c.strip()}
        keywords = self.conf.get_section_for_data('TOKEN', 'invalid_keywords')
        self.invalid_keywords = [k.strip() for k in (keywords or '').split(',') if k.strip()]

    def login(self):
        """
        调用登录接口，成功后把 token、过期时间、Cookie 写入内存。

        复用 data/loginName.yaml 的账号数据（baseInfo 的 url/header + testCase 的请求参数），
        使用独立的 requests 调用而不经过 SendRequest，避免登录请求自身触发 token 检查造成递归。

        :return: 登录接口响应 dict；失败抛出异常
        """
        with self._lock:
            api_info = get_testcase_yaml('./data/loginName.yaml')
            base_info, test_case = api_info[0][0], api_info[0][1]
            url = self.conf.get_section_for_data('api_envi', 'host') + base_info['url']
            params = {k: v for k, v in test_case.items() if k in ('data', 'json', 'params')}
            response = requests.request(method=base_info['method'], url=url,
                                        headers=base_info['header'], timeout=60, verify=False, **params)
            body = response.json()
            token = jsonpath.jsonpath(body, '$.token')
            if not token:
                raise RuntimeError('登录失败：响应中未提取到 token，响应为 %s' % body)
            self.token = token[0]
            self.token_expire_time = int(time.time()) + self.token_expire_seconds
            set_cookie = requests.utils.dict_from_cookiejar(response.cookies)
            if set_cookie:
                self.cookies = set_cookie
            logs.info('登录成功，token 已加载到内存（有效期 %s 秒）' % self.token_expire_seconds)
            return body

    def refresh_if_needed(self):
        """请求前检查：token 即将过期（不足 refresh_advance_seconds）时自动重新登录。"""
        if self.refreshing or not self.token:
            return
        if int(time.time()) >= self.token_expire_time - self.refresh_advance_seconds:
            logs.info('检测到 token 即将过期，自动刷新 token')
            self.login()

    def is_invalid_response(self, response):
        """
        判断接口响应是否为 token 失效。

        优先看 HTTP 状态码（401/403），再解析业务返回：
        - 业务错误码命中配置的 invalid_error_codes
        - 业务提示信息（msg/message/error）命中配置的关键词

        :param response: requests.Response 对象
        :return: bool，True 表示 token 已失效
        """
        if response is None:
            return False
        if response.status_code in self.invalid_status_codes:
            return True
        try:
            body = response.json()
        except Exception:
            return False
        if isinstance(body, dict):
            for key in ('error_code', 'code', 'errorCode'):
                if key in body and str(body[key]) in self.invalid_error_codes:
                    return True
            msg = ''.join(str(body.get(k) or '') for k in ('msg', 'message', 'error', 'Message'))
            if any(kw in msg for kw in self.invalid_keywords):
                return True
        return False

    def refresh_and_retry_token(self):
        """token 失效后重新登录。执行期间置 refreshing 标志防止递归。"""
        if self.refreshing:
            return None
        self.refreshing = True
        try:
            body = self.login()
            logs.info('token 刷新成功')
            return body.get('token')
        except Exception as e:
            logs.error('token 刷新异常：%s' % e)
            return None
        finally:
            self.refreshing = False

    def apply_auth(self, header=None, cookies=None):
        """
        把内存中的登录态注入请求：token 补进请求头，Cookie 合并进请求 cookies。

        :param header: 请求头 dict（可缺失）
        :param cookies: 调用方显式传入的 cookies dict（可缺失）
        :return: (header, cookies) 注入后的元组
        """
        header = header if isinstance(header, dict) else {}
        if self.token and 'token' not in header:
            header['token'] = self.token
        merged = dict(self.cookies) if self.cookies else {}
        if isinstance(cookies, dict):
            merged.update(cookies)
        return header, (merged or None)


# 模块级单例：整个 pytest 进程共享同一份登录态
AUTH = AuthState()
