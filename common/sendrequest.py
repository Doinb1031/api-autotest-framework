import json
import time

import allure
import jsonpath
import pytest
import requests
import urllib3

from conf import setting
from conf.operationConfig import OperationConfig
from common.recordlog import logs
from requests import utils
from common.readyaml import ReadYamlData, get_testcase_yaml
from requests.packages.urllib3.exceptions import InsecureRequestWarning


class SendRequest:
    """
    HTTP 请求发送封装类。

    基于 requests 库封装 GET/POST 请求，统一格式化响应结果，
    自动管理 Cookie 持久化，集成日志记录与 Allure 报告。
    """

    def __init__(self, cookie=None):
        """
        初始化 SendRequest 实例。

        :param cookie: 可选，初始 cookie 字典，用于携带登录态等
        """
        self.cookie = cookie
        # 创建 ReadYamlData 实例，用于将响应中的 cookie 持久化到 extract.yaml
        self.read = ReadYamlData()
        self.conf = OperationConfig()
        # 是否正在刷新 token（防止登录/刷新请求自身再次触发检查，造成递归）
        self._refreshing = False
        # 加载 token 失效处理配置
        self._init_token_config()

    def _init_token_config(self):
        """加载 [TOKEN] 配置段，用于两层 token 失效处理。"""
        # token 有效期（秒）
        expire = self.conf.get_section_for_data('TOKEN', 'expire_seconds')
        self.token_expire_seconds = int(expire) if expire.isdigit() else 3600
        # 提前刷新时间（秒），到期前多少秒触发自动刷新
        advance = self.conf.get_section_for_data('TOKEN', 'refresh_advance_seconds')
        self.refresh_advance_seconds = int(advance) if advance.isdigit() else 300
        # 判定 token 失效的 HTTP 状态码
        codes = self.conf.get_section_for_data('TOKEN', 'invalid_status_codes')
        self.invalid_status_codes = [int(c) for c in (codes or '401,403').split(',') if c.strip().isdigit()]
        # 判定 token 失效的业务错误码
        e_codes = self.conf.get_section_for_data('TOKEN', 'invalid_error_codes')
        self.invalid_error_codes = {c.strip() for c in (e_codes or '401,403').split(',') if c.strip()}
        # 判定 token 失效的业务提示关键词
        keywords = self.conf.get_section_for_data('TOKEN', 'invalid_keywords')
        self.invalid_keywords = [k.strip() for k in (keywords or '').split(',') if k.strip()]

    def _is_token_invalid(self, response):
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

    def ensure_token_valid(self):
        """
        第一层：请求前检查 token 是否即将过期，过期则自动刷新。

        逻辑：
        1. extract.yaml 中没有 token（首次登录前/非 token 鉴权接口）→ 不处理
        2. 有 token 但没有过期时间（旧数据）→ 从当前时刻开始记录有效期
        3. 距过期时间不足 refresh_advance_seconds → 自动重新登录刷新 token
        """
        if self._refreshing:
            return
        try:
            token = self.read.get_extract_yaml('token')
        except Exception:
            return
        if not token:
            return
        try:
            expire = int(self.read.get_extract_yaml('token_expire_time'))
        except Exception:
            # 只有 token 没有过期时间：视为刚登录，从当前时刻记录有效期
            self.read.write_yaml_data({'token_expire_time': int(time.time()) + self.token_expire_seconds})
            return
        if int(time.time()) >= expire - self.refresh_advance_seconds:
            logs.info('检测到 token 即将过期，自动刷新 token')
            self.login_and_refresh_token()

    def login_and_refresh_token(self):
        """
        调用登录接口刷新 token，并把新 token、过期时间写入 extract.yaml。

        复用 data/loginName.yaml 的登录用例数据，保证与 session 前置登录使用同一套数据。
        执行期间置 _refreshing 标志，避免登录请求自身触发 token 检查造成递归。

        :return: 新 token（str）；刷新失败返回 None
        """
        if self._refreshing:
            return None
        self._refreshing = True
        try:
            api_info = get_testcase_yaml('./data/loginName.yaml')
            base_info, test_case = api_info[0][0], api_info[0][1]
            url = self.conf.get_section_for_data('api_envi', 'host') + base_info['url']
            header = base_info['header']
            method = base_info['method']
            # 只取请求参数（data/json/params），跳过 case_name/validation/extract 等非请求字段
            params = {k: v for k, v in test_case.items() if k in ('data', 'json', 'params')}
            res = self.run_main(name=base_info['api_name'], url=url, case_name='token自动刷新-重新登录',
                                header=header, method=method, **params)
            token = jsonpath.jsonpath(res.json(), '$.token')
            if not token:
                logs.error('token 刷新失败：登录接口响应中未提取到 token')
                return None
            # 写入新 token 和过期时间（extract.yaml 重复 key 后者覆盖前者，取到的是最新值）
            self.read.write_yaml_data({'token': token[0]})
            self.read.write_yaml_data({'token_expire_time': int(time.time()) + self.token_expire_seconds})
            logs.info('token 刷新成功')
            return token[0]
        except Exception as e:
            logs.error('token 刷新异常：%s' % e)
            return None
        finally:
            self._refreshing = False

    def _replace_token_in_headers(self, header):
        """
        重试请求前，把 header 中的旧 token 替换成 extract.yaml 里的最新 token。

        :param header: 请求头（dict）
        :return: 替换后的请求头
        """
        try:
            new_token = self.read.get_extract_yaml('token')
            if new_token and isinstance(header, dict) and 'token' in header:
                header['token'] = new_token
        except Exception:
            pass
        return header


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

        :param url: 请求地址
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
        底层通用请求方法。使用 requests.session 发送请求，
        并自动将响应中的 Set-Cookie 持久化到 extract.yaml。

        :param kwargs: 透传给 session.request() 的所有参数（method, url, headers, data 等）
        :return: Response 对象；失败时调用 pytest.fail 中断测试
        """
        session = requests.session()
        result = None
        cookie = {}
        try:
            result = session.request(**kwargs)
            # 从响应中提取 cookie 并持久化，用于后续请求自动携带
            # 将响应中的 CookieJar 对象转换为普通字典，便于后续持久化
            set_cookie = requests.utils.dict_from_cookiejar(result.cookies)
            # 非空字典才写入，避免写入无意义的空 cookie
            if set_cookie:
                cookie['Cookie'] = set_cookie
                # 持久化 cookie 到 extract.yaml
                self.read.write_yaml_data(cookie)
                logs.info("cookie:%s" % cookie)
            logs.info("接口返回信息:%s" % result.text if result.text else result)
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
        最上层请求入口。统一记录日志、附加 Allure 报告信息，并执行请求。

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
            # 输出日志，便于调试和定位问题
            logs.info('接口名称：%s' % name)
            logs.info('请求地址：%s' % url)
            logs.info('请求方式：%s' % method)
            logs.info('测试用例名称：%s' % case_name)
            logs.info('请求头：%s' % header)
            logs.info('Cookie:%s' % cookies)
            # 转换 kwargs 为 JSON 字符串，用于 Allure 报告
            req_params = json.dumps(kwargs, ensure_ascii=False)
            # 根据参数类型附加到 Allure 报告并记录日志
            if "data" in kwargs.keys():
                allure.attach(req_params, '请求参数', allure.attachment_type.TEXT)
                logs.info("请求参数：%s" % kwargs)
            elif "json" in kwargs.keys():
                allure.attach(req_params, '请求参数', allure.attachment_type.TEXT)
                logs.info("请求参数：%s" % kwargs)
            elif "params" in kwargs.keys():
                allure.attach(req_params, '请求参数', allure.attachment_type.TEXT)
                logs.info("请求参数：%s" % kwargs)
        except Exception as e:
            logs.error(e)
        # 禁用警告，避免在测试报告中显示警告信息
        requests.packages.urllib3.disable_warnings(InsecureRequestWarning)
        # 第一层：请求前检查 token 是否即将过期，过期则自动刷新
        self.ensure_token_valid()
        response = self.send_request(method=method,
                                     url=url,
                                     headers=header,
                                     cookies=cookies,
                                     files=file,
                                     timeout=setting.API_TIMEOUT,
                                     verify=False,
                                     **kwargs)
        # 第二层：请求后检测 token 是否已失效，失效则自动刷新并重试一次
        # （最多重试 1 次，避免刷新失败后一直循环；_refreshing 期间不做检测，防止递归）
        if not self._refreshing and self._is_token_invalid(response):
            logs.info('接口返回 token 失效，自动刷新 token 并重试该请求')
            self.login_and_refresh_token()
            header = self._replace_token_in_headers(header)
            response = self.send_request(method=method,
                                         url=url,
                                         headers=header,
                                         cookies=cookies,
                                         files=file,
                                         timeout=setting.API_TIMEOUT,
                                         verify=False,
                                         **kwargs)
        return response
