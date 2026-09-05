"""
接口测试核心工具类模块

本模块是接口自动化测试的核心，主要提供以下功能：
1. yaml 数据中 ${函数名()} 占位符的解析与替换
2. 接口请求的完整处理流程（拼接 URL、处理请求头、参数、文件上传等）
3. 接口响应数据的提取（支持正则表达式和 jsonpath）
4. 接口断言校验
5. Allure 测试报告信息记录
"""
import json
import re
from json.decoder import JSONDecodeError

import allure
import jsonpath

from common.assertions import Assertions
from common.debugtalk import DebugTalk
from common.readyaml import get_testcase_yaml, ReadYamlData
from common.recordlog import logs
from common.sendrequest import SendRequest
from conf.operationConfig import OperationConfig
from conf.setting import FILE_PATH


class RequestBase:
    """接口请求处理基类，封装了从 yaml 用例到接口请求、响应提取、断言的完整流程"""

    def __init__(self):
        # 初始化各个工具对象，后续接口处理流程中会用到
        self.run = SendRequest()          # 发送 HTTP 请求的工具
        self.conf = OperationConfig()      # 读取配置文件的工具
        self.read = ReadYamlData()          # 接口提取变量读写（内存业务上下文）
        self.asserts = Assertions()        # 断言校验工具

    def replace_load(self, data):
        """
        yaml 数据替换解析

        作用：把 yaml 用例里的 ${函数名(参数)} 占位符，替换成 DebugTalk 中对应函数的返回值
        例如：${timestamp()}  会被替换成当前时间戳
             ${md5_encryption(123456)}  会被替换成加密后的字符串

        :param data: 原始数据，可以是字符串或字典
        :return: 替换后的数据，类型与传入时保持一致
        """
        str_data = data
        # 如果传入的不是字符串（比如是字典），先转成 json 字符串方便处理
        if not isinstance(data, str):
            str_data = json.dumps(data, ensure_ascii=False)
            # print('从yaml文件获取的原始数据：', str_data)
        # 循环次数 = 字符串中 ${ 的个数，即有多少个占位符就循环多少次
        for i in range(str_data.count('${')):
            if '${' in str_data and '}' in str_data:
                # 找到 $ 和 } 的位置
                start_index = str_data.index('$')
                end_index = str_data.index('}', start_index)
                # 取出整个占位符，例如 ${timestamp()}
                ref_all_params = str_data[start_index:end_index + 1]
                # 取出函数名：${ 之后、( 之前的部分
                func_name = ref_all_params[2:ref_all_params.index("(")]
                # 取出函数里面的参数：( 之后、) 之前的部分
                func_params = ref_all_params[ref_all_params.index("(") + 1:ref_all_params.index(")")]
                # 通过反射机制 getattr，用函数名从 DebugTalk 类中取出对应方法并调用
                # 相当于执行 DebugTalk().函数名(参数)
                extract_data = getattr(DebugTalk(), func_name)(*func_params.split(',') if func_params else "")

                # 如果返回值是列表，用逗号拼成字符串
                if extract_data and isinstance(extract_data, list):
                    extract_data = ','.join(e for e in extract_data)
                # 把占位符替换成实际值
                str_data = str_data.replace(ref_all_params, str(extract_data))
                # print('通过解析后替换的数据：', str_data)

        # 还原数据：如果原来是字典，就把 json 字符串转回字典
        if data and isinstance(data, dict):
            data = json.loads(str_data)
        else:
            data = str_data
        return data

    def specification_yaml(self, base_info, test_case):
        """
        接口请求处理基本方法：组装并发送请求，处理响应、提取、断言

        :param base_info: yaml 文件里面的 baseInfo（基础信息：url、method、header 等）
        :param test_case: yaml 文件里面的 testCase（测试用例：参数、断言、提取等）
        :return:
        """
        try:
            # 支持的请求参数类型
            params_type = ['data', 'json', 'params']
            # 从配置文件读取接口 host
            url_host = self.conf.get_section_for_data('api_envi', 'host')
            api_name = base_info['api_name']
            # 把接口名称记录到 allure 报告中
            allure.attach(api_name, f'接口名称：{api_name}', allure.attachment_type.TEXT)
            # 拼接完整 url = host + 路径
            url = url_host + base_info['url']
            allure.attach(api_name, f'接口地址：{url}', allure.attachment_type.TEXT)
            method = base_info['method']
            allure.attach(api_name, f'请求方法：{method}', allure.attachment_type.TEXT)
            # 处理请求头（可能包含 ${} 占位符需要替换）
            header = self.replace_load(base_info['header'])
            allure.attach(api_name, f'请求头：{header}', allure.attachment_type.TEXT)
            # 处理 cookie
            cookie = None
            if base_info.get('cookies') is not None:
                cookie = json.loads(self.replace_load(base_info['cookies']))
            # 从 test_case 中弹出 case_name（弹出后 test_case 不再有这个 key）
            case_name = test_case.pop('case_name')
            allure.attach(api_name, f'测试用例名称：{case_name}', allure.attachment_type.TEXT)
            # 处理断言：先替换占位符，再用 json.loads 把字符串转成列表
            val = self.replace_load(test_case.get('validation'))
            test_case['validation'] = val
            validation = json.loads(test_case.pop('validation'))
            # 处理参数提取（单个值 / 列表）
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
            res = self.run.run_main(name=api_name, url=url, case_name=case_name, header=header, method=method,
                                    file=files, cookies=cookie, **test_case)
            status_code = res.status_code
            # 把响应信息记录到 allure 报告
            allure.attach(self.allure_attach_response(res.json()), '接口响应信息', allure.attachment_type.TEXT)

            try:
                # 把响应文本转成字典
                res_json = json.loads(res.text)  # 把json格式转换成字典字典
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
                logs.error(e)
                raise e

        except Exception as e:
            raise e

    @classmethod
    def allure_attach_response(cls, response):
        """
        格式化响应信息，用于 allure 测试报告展示

        这个方法的作用是把接口返回的数据"美化"一下，再记录到 allure 报告中。
        因为 allure 是生成 HTML 报告的，如果直接记录一个 Python 字典，报告里显示的就是
        {'key': 'value'} 这种紧凑格式，看起来很不舒服。
        这个方法把字典转成带缩进的 JSON 字符串，报告里看起来就像格式化后的代码一样清晰。

        例子：
            输入：  {"code": 200, "data": {"name": "张三"}}
            输出：  {
                       "code": 200,
                       "data": {
                           "name": "张三"
                       }
                   }

        :param response: 接口响应数据，可以是 dict 或 str
        :return: 格式化后的字符串（如果传入的是 dict，返回带缩进的 JSON 字符串；
                 如果传入的本来就是字符串，原样返回）
        """
        if isinstance(response, dict):
            # 字典类型 → 转成带缩进(4个空格)、不转义中文的 JSON 字符串
            allure_response = json.dumps(response, ensure_ascii=False, indent=4)
        else:
            # 非字典（比如已经是字符串了）→ 直接返回，不改动
            allure_response = response
        return allure_response

    def extract_data(self, testcase_extarct, response):
        """
        提取接口的返回值中的某个字段（提取单个值），写入内存业务上下文 供后续接口使用

        这是接口自动化测试中"参数传递"的关键环节。
        比如:接口A返回了 {"token": "abc123"}，你想把这个 token 取出来传给接口B。
        方法里写了两种提取方式，写 yaml 时选一种就行：

        方式一：正则表达式提取
            yaml 里写：  extract:
                           token: '"token":"(.*?)"'
            意思是从响应字符串中，用正则 "token":"(.*?)" 匹配出 token 的值。

        方式二:jsonpath 提取
            yaml 里写：  extract:
                           token: $.data.token
            意思是从响应的 JSON 结构中，沿着 data → token 的路径取值。

        两种方式都会把提取结果以 {key: value} 的形式写入内存业务上下文。
        后续 yaml 用例中就可以通过 ${get_extract_data(key)} 拿到这个值。

        :param testcase_extarct: 从 testCase 中 pop 出来的 extract 字典
                                 格式如：{"token": '"token":"(.*?)"'}
        :param response: 接口响应的原始文本（字符串），用于正则匹配
        :return: 无返回值，提取结果直接写入内存业务上下文 文件
        """
        try:
            # 常见的正则匹配模式，用于判断 yaml 里写的是不是正则表达式
            # 如果 extract 的 value 里包含这些模式之一，就走正则提取
            pattern_lst = ['(.*?)', '(.+?)', r'(\d)', r'(\d*)']
            for key, value in testcase_extarct.items():
                # key 是提取结果的变量名（比如 "token"）
                # value 是提取表达式（正则 或 jsonpath）

                # ----- 方式一：正则表达式提取 -----
                for pat in pattern_lst:
                    if pat in value:
                        # 用 yaml 里写的正则去匹配响应字符串
                        ext_lst = re.search(value, response)
                        # ext_lst.group(1) 取出正则中第一个括号 () 匹配到的内容
                        if pat in [r'(\d+)', r'(\d*)']:
                            # 如果匹配的是数字格式，转成 int 类型存储
                            extract_data = {key: int(ext_lst.group(1))}
                        else:
                            # 否则按字符串类型存储
                            extract_data = {key: ext_lst.group(1)}
                        # 写入内存业务上下文
                        self.read.write_yaml_data(extract_data)

                # ----- 方式二：jsonpath 提取 -----
                if '$' in value:
                    # jsonpath 匹配成功返回列表，匹配失败返回 False，需先判空再取 [0]
                    ext_list = jsonpath.jsonpath(json.loads(response), value)
                    if ext_list:
                        ext_json = ext_list[0]
                        extarct_data = {key: ext_json}
                        logs.info('提取接口的返回值：%s' % extarct_data)
                    else:
                        # 提取不到就给个提示信息，避免程序崩溃
                        extarct_data = {key: '未提取到数据，请检查接口返回值是否为空！'}
                    self.read.write_yaml_data(extarct_data)
        except Exception as e:
            logs.error(e)

    def extract_data_list(self, testcase_extract_list, response):
        """
        提取接口返回值中的多个字段（提取结果以列表形式存储），写入内存业务上下文

        这个方法跟 extract_data 的区别：
          extract_data（单值提取）：
            - 正则用 re.search → 只匹配第一个结果
            - jsonpath 用 [0] → 只取第一个
            - 最终存到 yaml 的是单个值（字符串或数字）
          extract_data_list（多值提取）：
            - 正则用 re.findall → 匹配所有结果
            - jsonpath 不用 [0] → 返回整个列表
            - 最终存到 yaml 的是列表

        应用场景举例：
          接口返回了多个商品：{"goodsList": [{"id": 1}, {"id": 2}, {"id": 3}]}
          如果想提取所有 id，用 extract_list：
            yaml 里写：  extract_list:
                           goods_id_list: $.goodsList[*].id
          提取结果是一个列表 [1, 2, 3]，写入内存业务上下文

          后续 yaml 可以通过 ${get_extract_data(goods_id_list, 0)} 随机取一个 id，
          或者 ${get_extract_data(goods_id_list, -2)} 取全部。

        :param testcase_extract_list: 从 testCase 中 pop 出来的 extract_list 字典
                                       格式如：{"goodsId": "$.goodsList[*].goodsId"}
        :param response: 接口响应的原始文本（字符串），用于正则匹配
        :return: 无返回值，提取结果直接写入内存业务上下文 文件
        """
        try:
            for key, value in testcase_extract_list.items():
                # ----- 方式一：正则表达式提取（取所有匹配项）-----
                if "(.+?)" in value or "(.*?)" in value:
                    # re.findall 匹配所有结果，返回列表
                    # re.S 让 . 也能匹配换行符，防止响应跨行时漏掉
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
        except:
            logs.error('接口返回值提取异常，请检查yaml文件extract_list表达式是否正确！')


if __name__ == '__main__':
    """
    调试入口：直接运行本文件时，读取 LoginAPI/login.yaml 的第一个用例并执行

    用法：
        python apiutil.py
    就会自动读取 login.yaml 用例，执行接口请求并打印结果。
    这主要用于开发调试，平时跑测试是靠 pytest 框架来调用。
    """
    # 读取 yaml 文件，get_testcase_yaml 返回列表，[0] 取第一个用例
    case_info = get_testcase_yaml(FILE_PATH['YAML'] + '/LoginAPI/login.yaml')[0]
    # print(case_info)  # 调试时可取消注释，查看 yaml 原始数据

    # 创建 RequestBase 对象
    req = RequestBase()
    # res = req.specification_yaml(case_info)  # 这句被注释掉了（可能是旧代码）
    res = req.specification_yaml(case_info)     # 执行接口请求
    print(res)  # 打印执行结果（由于方法没有 return，实际打印的是 None）
