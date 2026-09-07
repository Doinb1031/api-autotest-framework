"""
接口测试核心执行器（唯一版本）。

2026-09 合并说明：本文件此前与 base/apiutil_business.py 是两套 80% 代码重复的执行器
（单用例版 / 多用例版），已知 bug 两边各修了一半（提取正则 (\\d) vs (\\d+)）。
现合并为一个 RequestBase：

- specification_yaml(base_info, test_case)   执行单个 testCase（数据驱动用例入口）
- specification_yaml_suite(case_info)        执行完整 case_info（baseInfo + testCase 列表），
                                             内部逐条调用 specification_yaml（业务链路用例入口）

两类 YAML 都走同一条 请求 → 提取 → 断言 代码路径，行为不再分叉。
"""
import json
import re

import allure
import jsonpath

from common.sendrequest import SendRequest
from common.auth import AUTH
from common.readyaml import ReadYamlData
from common.recordlog import logs
from conf.operationConfig import OperationConfig
from common.assertions import Assertions
from common.debugtalk import DebugTalk
from json.decoder import JSONDecodeError


class RequestBase(object):
    """接口请求处理类：解析 YAML 用例 → 组装请求 → 发送 → 提取参数 → 断言"""

    def __init__(self):
        self.run = SendRequest()          # 发送 HTTP 请求的工具
        self.read = ReadYamlData()        # 接口提取变量读写（内存业务上下文）
        self.conf = OperationConfig()     # 读取配置文件的工具
        self.asserts = Assertions()       # 断言工具

    # ---------- ${} 占位符解析 ----------

    def handler_yaml_list(self, data_dict):
        """
        把请求参数中 list 类型的值统一转成字符串列表。

        作用是保证列表元素都是字符串类型：[1, 2, 3] → ["1", "2", "3"]。

        :param data_dict: 请求参数字典（原地修改）
        :return: 处理后的字典
        """
        for key, value in data_dict.items():
            if isinstance(value, list):
                # str() 逐元素转换，避免 int 元素导致 join 报错
                data_dict[key] = ','.join(str(item) for item in value).split(',')
        return data_dict

    def replace_load(self, data):
        """
        yaml 数据替换解析。

        把 yaml 用例里的 ${函数名(参数)} 占位符，替换成 DebugTalk 中对应函数的返回值。
        例如：${timestamp()} → 当前时间戳；${get_extract_data(goodsId)} → 内存上下文中的变量。
        支持占位符内嵌在字符串中间（如 "testuser_${timestamp()}"）。

        :param data: 原始数据，可以是字符串或字典
        :return: 替换后的数据，类型与传入时保持一致
        """
        str_data = data
        # 如果传入的不是字符串（比如是字典），先转成 json 字符串方便处理
        if not isinstance(data, str):
            str_data = json.dumps(data, ensure_ascii=False)
        # 循环次数 = 字符串中 ${ 的个数，即有多少个占位符就循环多少次
        for i in range(str_data.count('${')):
            if '${' in str_data and '}' in str_data:
                # 找到 $ 和 } 的位置，取出整个占位符，例如 ${timestamp()}
                start_index = str_data.index('$')
                end_index = str_data.index('}', start_index)
                ref_all_params = str_data[start_index:end_index + 1]
                # 取出函数名（${ 之后、( 之前）和参数（( 之后、) 之前）
                func_name = ref_all_params[2:ref_all_params.index("(")]
                func_params = ref_all_params[ref_all_params.index("(") + 1:ref_all_params.index(")")]
                # 反射调用 DebugTalk 中的对应方法
                extract_data = getattr(DebugTalk(), func_name)(*func_params.split(',') if func_params else "")
                # 如果返回值是列表，用逗号拼成字符串
                if extract_data and isinstance(extract_data, list):
                    extract_data = ','.join(e for e in extract_data)
                # 把占位符替换成实际值
                str_data = str_data.replace(ref_all_params, str(extract_data))

        # 还原数据：如果原来是字典，就把 json 字符串转回字典
        if data and isinstance(data, dict):
            data = json.loads(str_data)
            self.handler_yaml_list(data)
        else:
            data = str_data
        return data

    # ---------- 用例执行入口 ----------

    def specification_yaml_suite(self, case_info):
        """
        执行链路式 YAML（baseInfo + testCase 列表），逐条 testCase 调用 specification_yaml。

        兼容 get_testcase_yaml 的三种返回形态：
        - 单个文档 dict：{'baseInfo': {...}, 'testCase': [...]}（多文档 yaml 经 parametrize 拆分后）
        - 文档 dict 列表：[{'baseInfo': ...}, ...]（多文档 yaml 原始返回）
        - [base_info, testCase] 配对列表（单文档 yaml 的返回）

        :param case_info: 上述任一形态
        :return: 无返回值，断言失败会抛出 AssertionError
        """
        if isinstance(case_info, dict):
            case_info = [case_info]
        for item in case_info:
            if isinstance(item, dict) and 'baseInfo' in item and 'testCase' in item:
                # 一个接口文档：文档内多条 testCase 共用 baseInfo
                base_info = item['baseInfo']
                for tc in item['testCase']:
                    self.specification_yaml(base_info, tc)
            elif isinstance(item, list) and len(item) == 2:
                # [base_info, test_case] 配对
                self.specification_yaml(item[0], item[1])
            else:
                raise ValueError(f'无法识别的用例数据结构：{type(item)}')

    def specification_yaml(self, base_info, test_case):
        """
        执行单个 testCase：组装并发送请求，处理响应、提取、断言。

        :param base_info: yaml 文件里面的 baseInfo（基础信息：url、method、header 等）
        :param test_case: yaml 文件里面的单条 testCase（case_name、请求参数、extract、validation）
        :return: None，断言失败会抛出 AssertionError
        """
        # 浅拷贝，避免 pop('case_name') 等操作污染调用方持有的原始数据
        # （parametrize 的参数对象在收集阶段就被创建，重复执行同一条用例时必须不受污染）
        test_case = dict(test_case)
        # 请求前刷新必须先于 ${} 占位符替换：若 header/data 里写了 ${get_auth_token()}，
        # 刷新发生在替换之后就会让占位符解析到旧 token（刷新后服务端已作废它），
        # 导致请求先失败再靠重试兜底；先刷新能保证占位符永远解析到最新 token。
        AUTH.refresh_if_needed()
        try:
            # 支持的请求参数类型
            params_type = ['data', 'json', 'params']
            # 从配置文件读取当前环境的接口 host（多环境：TEST_ENV/--env 决定读哪个段）
            url_host = self.conf.get_api_env('host')
            api_name = base_info['api_name']
            # 拼接完整 url = host + 路径
            url = url_host + base_info['url']
            allure.attach(api_name, f'接口名称：{api_name}', allure.attachment_type.TEXT)
            allure.attach(api_name, f'接口地址：{url}', allure.attachment_type.TEXT)
            method = base_info['method']
            allure.attach(api_name, f'请求方法：{method}', allure.attachment_type.TEXT)
            # 处理请求头（可能包含 ${} 占位符需要替换）
            header = self.replace_load(base_info['header'])
            allure.attach(api_name, f'请求头：{header}', allure.attachment_type.TEXT)
            # 处理 cookie（yaml 里没有 cookies 字段时跳过）
            cookie = None
            if base_info.get('cookies') is not None:
                cookie = json.loads(self.replace_load(base_info['cookies']))
            case_name = test_case.pop('case_name')
            allure.attach(api_name, f'测试用例名称：{case_name}', allure.attachment_type.TEXT)
            # 处理断言：先替换占位符，再用 json.loads 把字符串转成列表
            val = self.replace_load(test_case.get('validation'))
            test_case['validation'] = val
            validation = json.loads(test_case.pop('validation'))
            allure.attach(str([str(list(i.values())) for i in validation]), "预期结果", allure.attachment_type.TEXT)
            # 处理参数提取（单个值 / 列表），不属于请求参数，要先 pop 出来
            extract = test_case.pop('extract', None)
            extract_list = test_case.pop('extract_list', None)
            # 处理接口的请求参数：遍历 test_case，对 data/json/params 三种参数做占位符替换
            for key, value in test_case.items():
                if key in params_type:
                    test_case[key] = self.replace_load(value)

            # 处理文件上传接口
            file, files = test_case.pop('files', None), None
            if file is not None:
                for fk, fv in file.items():
                    allure.attach(json.dumps(file), '导入文件')
                    # 以二进制读模式打开文件，用于上传
                    files = {fk: open(fv, mode='rb')}

            # 发送请求：把所有参数传给 SendRequest 执行真正的 HTTP 请求
            try:
                res = self.run.run_main(name=api_name, url=url, case_name=case_name, header=header, method=method,
                                        file=files, cookies=cookie, **test_case)
            finally:
                # 请求完成后关闭上传文件句柄，避免文件描述符泄漏
                if files:
                    for fh in files.values():
                        fh.close()
            status_code = res.status_code
            # 把响应信息记录到 allure 报告
            allure.attach(self.allure_attach_response(res.json()), '接口响应信息', allure.attachment_type.TEXT)

            try:
                # 把响应文本转成字典
                res_json = json.loads(res.text)
                # 参数提取（单个值）
                if extract is not None:
                    self.extract_data(extract, res.text)
                # 参数提取（列表）
                if extract_list is not None:
                    self.extract_data_list(extract_list, res.text)
                # 断言校验
                self.asserts.assert_result(validation, res_json, status_code)
            except JSONDecodeError as js:
                logs.error('系统异常或接口未请求！')
                raise js

        except Exception as e:
            raise e

    @classmethod
    def allure_attach_response(cls, response):
        """
        格式化响应信息，用于 allure 测试报告展示。

        把字典转成带缩进(4个空格)、不转义中文的 JSON 字符串，
        报告里看起来就像格式化后的代码一样清晰；非 dict 原样返回。
        """
        if isinstance(response, dict):
            allure_response = json.dumps(response, ensure_ascii=False, indent=4)
        else:
            allure_response = response
        return allure_response

    # ---------- 参数提取 ----------

    def extract_data(self, testcase_extarct, response):
        """
        提取接口返回值中的单个字段，写入内存业务上下文 供后续接口使用。

        这是接口自动化测试中"参数传递"的关键环节。
        比如:接口A返回了 {"token": "abc123"}，把这个 token 取出来传给接口B。
        方法里写了两种提取方式，写 yaml 时选一种就行：

        方式一：正则表达式提取
            yaml 里写：  extract:
                           token: '"token":"(.*?)"'
            从响应字符串中，用正则 "token":"(.*?)" 匹配出 token 的值。

        方式二:jsonpath 提取
            yaml 里写：  extract:
                           token: $.data.token
            从响应的 JSON 结构中，沿着 data → token 的路径取值。

        两种方式都会把提取结果以 {key: value} 的形式写入内存业务上下文。
        后续 yaml 用例中就可以通过 ${get_extract_data(key)} 拿到这个值。

        :param testcase_extarct: 从 testCase 中 pop 出来的 extract 字典
                                 格式如：{"token": '"token":"(.*?)"'}
        :param response: 接口响应的原始文本（字符串），用于正则匹配
        :return: 无返回值，提取结果直接写入内存业务上下文
        """
        # 常见的正则匹配模式，用于判断 yaml 里写的是不是正则表达式
        # 如果 extract 的 value 里包含这些模式之一，就走正则提取
        pattern_lst = ['(.*?)', '(.+?)', r'(\d+)', r'(\d*)']
        try:
            for key, value in testcase_extarct.items():
                # ----- 方式一：正则表达式提取 -----
                for pat in pattern_lst:
                    if pat in value:
                        # 用 yaml 里写的正则去匹配响应字符串
                        ext_lst = re.search(value, response)
                        if ext_lst is None:
                            logs.error('正则提取失败：表达式【%s】在响应中未匹配到内容' % value)
                            continue
                        # ext_lst.group(1) 取出正则中第一个括号 () 匹配到的内容
                        if pat in [r'(\d+)', r'(\d*)']:
                            # 如果匹配的是数字格式，转成 int 类型存储
                            extract_data = {key: int(ext_lst.group(1))}
                        else:
                            # 否则按字符串类型存储
                            extract_data = {key: ext_lst.group(1)}
                        logs.info('正则提取到的参数：%s' % extract_data)
                        # 写入内存业务上下文
                        self.read.write_yaml_data(extract_data)

                # ----- 方式二：jsonpath 提取 -----
                if '$' in value:
                    # jsonpath 匹配成功返回列表，匹配失败返回 False，需先判空再取 [0]
                    ext_list = jsonpath.jsonpath(json.loads(response), value)
                    if ext_list:
                        extarct_data = {key: ext_list[0]}
                        logs.info('提取接口的返回值：%s' % extarct_data)
                    else:
                        # 提取不到就给个提示信息，避免程序崩溃
                        extarct_data = {key: '未提取到数据，请检查接口返回值是否为空！'}
                    self.read.write_yaml_data(extarct_data)
        except Exception as e:
            logs.error('接口返回值提取异常，请检查yaml文件extract表达式是否正确：%s' % e)

    def extract_data_list(self, testcase_extract_list, response):
        """
        提取接口返回值中的多个字段（提取结果以列表形式存储），写入内存业务上下文。

        与 extract_data 的区别：
          extract_data（单值提取）：正则用 re.search / jsonpath 取 [0]，存单个值
          extract_data_list（多值提取）：正则用 re.findall / jsonpath 返回整个列表

        应用场景举例：
          接口返回了多个商品：{"goodsList": [{"id": 1}, {"id": 2}]}
          yaml 里写：  extract_list:
                         goodsId: $.goodsList[*].goodsId
          提取结果是列表，写入内存业务上下文；
          后续 yaml 可以通过 ${get_extract_data(goodsId, 0)} 随机取一个。

        :param testcase_extract_list: 从 testCase 中 pop 出来的 extract_list 字典
                                       格式如：{"goodsId": "$.goodsList[*].goodsId"}
        :param response: 接口响应的原始文本（字符串），用于正则匹配
        :return: 无返回值，提取结果直接写入内存业务上下文
        """
        try:
            for key, value in testcase_extract_list.items():
                # ----- 方式一：正则表达式提取（取所有匹配项）-----
                if "(.+?)" in value or "(.*?)" in value:
                    # re.findall 匹配所有结果；re.S 让 . 也能匹配换行符，防止响应跨行时漏掉
                    ext_list = re.findall(value, response, re.S)
                    if ext_list:
                        extract_date = {key: ext_list}
                        logs.info('正则提取到的参数：%s' % extract_date)
                        self.read.write_yaml_data(extract_date)

                # ----- 方式二：jsonpath 提取（取所有匹配值）-----
                if "$" in value:
                    # 注意这里没有 [0]，所以返回的是整个列表
                    ext_json = jsonpath.jsonpath(json.loads(response), value)
                    if ext_json:
                        extract_date = {key: ext_json}
                    else:
                        # 提取不到给个默认值，防止后续用例调用 get_extract_data 时报错
                        extract_date = {key: "未提取到数据，该接口返回结果可能为空"}
                    logs.info('json提取到参数：%s' % extract_date)
                    self.read.write_yaml_data(extract_date)
        except Exception as e:
            logs.error('接口返回值提取异常，请检查yaml文件extract_list表达式是否正确：%s' % e)
