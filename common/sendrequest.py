import json
import re
import time

import allure
import jsonpath
import pytest
import requests
import urllib3

from conf import setting
from conf.operationConfig import OperationConfig
from common.auth import AUTH
from common.recordlog import logs
from requests import utils
from common.readyaml import ReadYamlData, get_testcase_yaml
from requests.packages.urllib3.exceptions import InsecureRequestWarning

# 敏感字段掩码规则：token / access_token_cookie 只保留前 4 位，避免明文泄入日志和测试报告
_MASK_PATTERNS = [
    (re.compile(r'("token"\s*:\s*")([^"]{0,4})[^"]*(")', re.IGNORECASE), r'\g<1>\g<2>****\g<3>'),
    (re.compile(r"(token['\"]?\s*[:=]\s*['\"]?)([^'\",}&\s]{0,4})[^'\",}&\s]*", re.IGNORECASE), r'\g<1>\g<2>****'),
    (re.compile(r'(access_token_cookie[=":\s]+)([\w.-]{0,4})[\w.-]*', re.IGNORECASE), r'\g<1>\g<2>****'),
]


def mask_sensitive(text):
    """掩码文本中的敏感值（token、access_token_cookie），非字符串原样返回。"""
    if not isinstance(text, str):
        return text
    for pattern, repl in _MASK_PATTERNS:
        text = pattern.sub(repl, text)
    return text


class SendRequest:
    """
    HTTP 请求发送封装类。

    基于 requests 库封装 GET/POST 请求，统一格式化响应结果，
    登录态（token/Cookie）由 common/auth.py 的内存 AuthState 统一注入，
    集成日志记录与 Allure 报告，敏感值自动掩码。
    """

    def __init__(self, cookie=None):
        """
        初始化 SendRequest 实例。

        :param cookie: 可选，初始 cookie 字典，用于携带登录态等
        """
        self.cookie = cookie
        # 创建 ReadYamlData 实例，用于业务数据提取（内存业务上下文）
        self.read = ReadYamlData()
        self.conf = OperationConfig()

    def get(self, url, data, header):
        """
        发送 GET 请求。

        :param url: 请求地址
        :param data: 请求参数(query string 参数）
        :param header: 请求头
        :return: dict,包含 code/text/body/res_ms/res_second:失败返回 None
        """
        requests.packages.urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        try:
            if data is None:
                response = requests.get(url, headers=header, cookies=self.cookie, verify=False)
            else:
                response = requests.get(url, data, headers=header, cookies=self.cookie, verify=False)
        except requests.RequestException as e:
            logs.error(e)
            return None
        except Exception as e:
            logs.error(e)
            return None
        # 计算响应时间
        res_ms = response.elapsed.microseconds / 1000       # 毫秒
        res_second = response.elapsed.total_seconds()       # 秒
        response_dict = dict()
        response_dict['code'] = response.status_code         # HTTP 状态码
        response_dict['text'] = response.text                # 原始响应文本
        try:
            response_dict['body'] = response.json().get('body')  # 尝试提取 body 字段
        except Exception:
            response_dict['body'] = ''
        response_dict['res_ms'] = res_ms
        response_dict['res_second'] = res_second
        return response_dict

    def post(self, url, data, header):
        """
        发送 POST 请求。

        :param url: 请求体参数
        :param data: 请求体参数
        :param header: 请求头
        :return: dict，包含 code/text/body/res_ms/res_second；失败返回 None
        """
        requests.packages.urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        try:
            if data is None:
                response = requests.post(url, headers=header, cookies=self.cookie, verify=False)
            else:
                response = requests.post(url, data, headers=header, cookies=self.cookie, verify=False)
        except requests.RequestException as e:
            logs.error(e)
            return None
        except Exception as e:
            logs.error(e)
            return None
        res_ms = response.elapsed.microseconds / 1000
        res_second = response.elapsed.total_seconds()
        response_dict = dict()
        response_dict['code'] = response.status_code
        response_dict['text'] = response.text
        try:
            response_dict['body'] = response.json().get('body')
        except Exception:
            response_dict['body'] = ''
        response_dict['res_ms'] = res_ms
        response_dict['res_second'] = res_second
        return response_dict

    def send_request(self, **kwargs):
        """
        底层通用请求方法。发送请求并把响应中的 Set-Cookie 合并进内存登录态。

        :param kwargs: 透传给 session.request() 的所有参数（method, url, headers, data 等）
        :return: Response 对象；失败时调用 pytest.fail 中断测试
        """
        session = requests.session()
        result = None
        try:
            result = session.request(**kwargs)
            # 响应中的 Set-Cookie 合并进内存登录态，供后续请求自动携带（不再落盘）
            set_cookie = requests.utils.dict_from_cookiejar(result.cookies)
            if set_cookie:
                AUTH.cookies.update(set_cookie)
                logs.info("cookie:%s" % mask_sensitive(str(set_cookie)))
            logs.info("接口返回信息:%s" % mask_sensitive(result.text) if result.text else result)
        except requests.exceptions.ConnectionError:
            logs.error("ConnectionError--连接异常")
            pytest.fail("接口请求异常，可能是request的连接数过多或请求速度过快导致程序报错！")
        except requests.exceptions.HTTPError:
            logs.error("HTTPError--http异常")
        except requests.exceptions.RequestException as e:
            logs.error(e)
            pytest.fail("请求异常，请检查系统或数据是否正常！")
        return result

    def run_main(self, name, url, case_name, header, method, cookies=None, file=None, **kwargs):
        """
        最上层请求入口。统一记录日志（敏感值掩码）、附加 Allure 报告信息，
        请求前从内存登录态注入 token/Cookie 并检查是否临近过期，执行请求。

        :param name: 接口名称（日志/报告用）
        :param url: 请求地址
        :param case_name: 测试用例名称
        :param header: 请求头
        :param method: 请求方法（get/post 等）
        :param cookies: 请求 cookie，默认为空
        :param file: 上传文件，默认为空
        :param kwargs: 请求参数，支持 data/json/params 等
        :return: Response 对象
        """

        try:
            # 输出日志，便于调试和定位问题（注入 token 之前记录，日志中不含 token）
            logs.info('接口名称：%s' % name)
            logs.info('请求地址：%s' % url)
            logs.info('请求方式：%s' % method)
            logs.info('测试用例名称：%s' % case_name)
            logs.info('请求头：%s' % header)
            # 转换 kwargs 为 JSON 字符串，用于 Allure 报告
            req_params = mask_sensitive(json.dumps(kwargs, ensure_ascii=False))
            # 根据参数类型附加到 Allure 报告并记录日志
            if "data" in kwargs.keys():
                allure.attach(req_params, '请求参数', allure.attachment_type.TEXT)
                logs.info("请求参数：%s" % mask_sensitive(str(kwargs)))
            elif "json" in kwargs.keys():
                allure.attach(req_params, '请求参数', allure.attachment_type.TEXT)
                logs.info("请求参数：%s" % mask_sensitive(str(kwargs)))
            elif "params" in kwargs.keys():
                allure.attach(req_params, '请求参数', allure.attachment_type.TEXT)
                logs.info("请求参数：%s" % mask_sensitive(str(kwargs)))
        except Exception as e:
            logs.error(e)
        # 禁用警告，避免在测试报告中显示警告信息
        requests.packages.urllib3.disable_warnings(InsecureRequestWarning)
        # 第一层：请求前检查内存登录态是否即将过期，过期则自动重新登录
        AUTH.refresh_if_needed()
        # 从内存登录态注入 token 到请求头、合并 Cookie
        header, cookies = AUTH.apply_auth(header, cookies)
        response = self.send_request(method=method,
                                     url=url,
                                     headers=header,
                                     cookies=cookies,
                                     files=file,
                                     timeout=setting.API_TIMEOUT,
                                     verify=False,
                                     **kwargs)
        # 第二层：请求后检测 token 是否已失效，失效则自动重新登录并重试一次
        # （最多重试 1 次，避免刷新失败后一直循环；refreshing 期间不做检测，防止递归）
        if not AUTH.refreshing and AUTH.is_invalid_response(response):
            logs.info('接口返回 token 失效，自动刷新 token 并重试该请求')
            old_token = AUTH.token
            AUTH.refresh_and_retry_token()
            # 请求参数体里若带有刷新前的旧 token（如 YAML 里 ${get_auth_token()} 替换后的值），
            # 必须同步换成新 token 再重试，否则服务端校验参数体 token 仍然失败。
            # 只替换"与旧 token 相等"的值，不影响缺 token/空 token 的负向用例语义。
            if old_token and AUTH.token and AUTH.token != old_token:
                for payload_key in ('data', 'json', 'params'):
                    payload = kwargs.get(payload_key)
                    if isinstance(payload, dict) and payload.get('token') == old_token:
                        payload['token'] = AUTH.token
            header = {k: v for k, v in header.items() if k != 'token'}
            header, cookies = AUTH.apply_auth(header, cookies)
            response = self.send_request(method=method,
                                         url=url,
                                         headers=header,
                                         cookies=cookies,
                                         files=file,
                                         timeout=setting.API_TIMEOUT,
                                         verify=False,
                                         **kwargs)
        return response
