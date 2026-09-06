# -*- coding: utf-8 -*-
r"""
接口测试业务处理模块（多用例版本）

本模块和 apiutil.py 功能基本一致，都是接口自动化测试的核心处理类。
主要区别：
1. specification_yaml 方法接收完整的 case_info（含 baseInfo + testCase 列表），
   而不是分开传 base_info 和 test_case
2. 支持一次处理多个 testCase（一个 yaml 文件可以写多个测试用例）
3. 多了 handler_yaml_list 方法，用于处理请求参数为 list 的情况
4. replace_load 还原字典后会额外调用 handler_yaml_list 处理列表参数
5. cookie 处理用 try-except 包裹（而非 if 判断）
6. extract_data 的正则模式列表中 r'(\d+)' 是正确的（apiutil.py 中有 bug 写成了 r'(\d)')

使用场景：当一个 yaml 文件包含多个测试用例时，用这个版本更合适。
"""
# sys.path.insert(0, "..")


from common.sendrequest import SendRequest
from common.readyaml import ReadYamlData
from common.recordlog import logs
from conf.operationConfig import OperationConfig
from common.assertions import Assertions
from common.debugtalk import DebugTalk
import allure
import json
import jsonpath
import re
import traceback
from json.decoder import JSONDecodeError

# 模块级别的断言对象，所有 RequestBase 实例共用一个
# （与 apiutil.py 不同，那里是在 __init__ 里创建实例属性）
assert_res = Assertions()


class RequestBase(object):
    """接口请求处理类，支持一个 yaml 文件包含多个 testCase 的场景"""

    def __init__(self):
        # 初始化各个工具对象
        self.run = SendRequest()          # 发送 HTTP 请求的工具
        self.read = ReadYamlData()        # 接口提取变量读写（内存业务上下文）
        self.conf = OperationConfig()     # 读取配置文件的工具

    def handler_yaml_list(self, data_dict):
        """
        处理 yaml 文件测试用例请求参数为 list 的情况

        当 yaml 里的某个参数值是列表时，会先 join 成字符串再 split 回列表。
        看似多此一举，实际作用是：保证列表元素都是字符串类型。
        比如原列表 [1, 2, 3] → "1,2,3" → ["1", "2", "3"]（全部变成字符串）

        :param data_dict: 请求参数字典
        :return: 处理后的字典
        """
        try:
            for key, value in data_dict.items():
                if isinstance(value, list):
                    # 先用逗号拼成字符串，再用逗号拆成列表
                    # 这一步会把所有元素统一转成字符串类型
                    value_lst = ','.join(value).split(',')
                    data_dict[key] = value_lst
                return data_dict
        except Exception:
            logs.error(str(traceback.format_exc()))

    def replace_load(self, data):
        """
        yaml 数据替换解析

        作用：把 yaml 用例里的 ${函数名(参数)} 占位符，替换成 DebugTalk 中对应函数的返回值
        和 apiutil.py 中的 replace_load 几乎一样，区别是还原字典后会调用 handler_yaml_list

        :param data: 原始数据，可以是字符串或字典
        :return: 替换后的数据，类型与传入时保持一致
        """
        str_data = data
        # 如果传入的不是字符串（比如是字典），先转成 json 字符串方便处理
        if not isinstance(data, str):
            str_data = json.dumps(data, ensure_ascii=False)
        # 循环次数 = 字符串中 ${ 的个数
        for i in range(str_data.count('${')):
            if '${' in str_data and '}' in str_data:
                # index 检测字符串是否包含子字符串，并返回索引位置
                start_index = str_data.index('$')
                end_index = str_data.index('}', start_index)
                # 取出整个占位符，如 ${get_yaml_data(loginname)}
                ref_all_params = str_data[start_index:end_index + 1]
                # 取出函数名：${ 之后、( 之前的部分
                func_name = ref_all_params[2:ref_all_params.index("(")]
                # 取出函数里的参数：( 之后、) 之前的部分
                func_params = ref_all_params[ref_all_params.index("(") + 1:ref_all_params.index(")")]
                # 通过反射机制 getattr 调用 DebugTalk 中的对应方法
                # *func_params.split(',') 把参数按逗号分割后解包传入
                extract_data = getattr(DebugTalk(), func_name)(*func_params.split(',') if func_params else "")
                # 如果返回值是列表，用逗号拼成字符串
                if extract_data and isinstance(extract_data, list):
                    extract_data = ','.join(e for e in extract_data)
                # 把占位符替换成实际值
                str_data = str_data.replace(ref_all_params, str(extract_data))
        # 还原数据：如果原来是字典，就把 json 字符串转回字典
        if data and isinstance(data, dict):
            data = json.loads(str_data)
            # 与 apiutil.py 的区别：还原字典后调用 handler_yaml_list 处理列表参数
            self.handler_yaml_list(data)
        else:
            data = str_data
        return data

    def specification_yaml(self, case_info):
        """
        规范 yaml 测试用例的写法：组装并发送请求，处理响应、提取、断言

        与 apiutil.py 的区别：
        - apiutil.py：接收 base_info 和 test_case 两个参数，只处理一个用例
        - 本方法：接收完整的 case_info（含 baseInfo + testCase 列表），
          用 for 循环遍历 testCase 中的每个用例，支持一个 yaml 文件多个用例

        :param case_info: list 类型，调试时取 case_info[0] 得到 dict
                          结构如：[{"baseInfo": {...}, "testCase": [{...}, {...}]}]
        :return: 无返回值
        """
        params_type = ['params', 'data', 'json']
        cookie = None
        try:
            # ----- 1. 处理 baseInfo（接口基础信息，所有 testCase 共用）-----
            base_url = self.conf.get_section_for_data('api_envi', 'host')
            # base_url = self.replace_load(case_info['baseInfo']['url'])
            url = base_url + case_info["baseInfo"]["url"]
            allure.attach(url, f'接口地址：{url}')
            api_name = case_info["baseInfo"]["api_name"]
            allure.attach(api_name, f'接口名：{api_name}')
            method = case_info["baseInfo"]["method"]
            allure.attach(method, f'请求方法：{method}')
            header = self.replace_load(case_info["baseInfo"]["header"])
            allure.attach(str(header), '请求头信息', allure.attachment_type.TEXT)

            # 处理 cookie（用 try-except 包裹，与 apiutil.py 的 if 判断不同）
            try:
                cookie = self.replace_load(case_info["baseInfo"]["cookies"])
                allure.attach(str(cookie), 'Cookie', allure.attachment_type.TEXT)
            except:
                # 如果 yaml 里没有 cookies 字段，replace_load 会报错，这里静默跳过
                pass

            # ----- 2. 遍历每个 testCase（一个 yaml 可以有多个测试用例）-----
            for tc in case_info["testCase"]:
                case_name = tc.pop("case_name")
                allure.attach(case_name, f'测试用例名称：{case_name}', allure.attachment_type.TEXT)

                # 断言结果解析替换：先替换 ${} 占位符
                val = self.replace_load(tc.get('validation'))
                tc['validation'] = val
                # replace_load 返回的是 JSON 字符串，用 json.loads 还原为 list
                # （原先用 eval 解析，无法处理 JSON 布尔值 true/false 且存在代码注入风险）
                validation = json.loads(tc.pop('validation'))
                # 把 validation 格式化成更易读的字符串记录到 allure 报告
                allure_validation = str([str(list(i.values())) for i in validation])
                allure.attach(allure_validation, "预期结果", allure.attachment_type.TEXT)

                # 取出 extract 和 extract_list（不是请求参数，要先 pop 出来）
                extract = tc.pop('extract', None)
                extract_lst = tc.pop('extract_list', None)

                # 处理请求参数：对 data/json/params 三种参数做占位符替换
                for key, value in tc.items():
                    if key in params_type:
                        tc[key] = self.replace_load(value)

                # 处理文件上传
                file, files = tc.pop("files", None), None
                if file is not None:
                    for fk, fv in file.items():
                        allure.attach(json.dumps(file), '导入文件')
                        files = {fk: open(fv, 'rb')}

                # ----- 3. 发送 HTTP 请求 -----
                try:
                    res = self.run.run_main(name=api_name,
                                            url=url,
                                            case_name=case_name,
                                            header=header,
                                            cookies=cookie,
                                            method=method,
                                            file=files, **tc)
                finally:
                    # 请求完成后关闭上传文件句柄，避免文件描述符泄漏
                    if files:
                        for fh in files.values():
                            fh.close()
                res_text = res.text
                allure.attach(res_text, '接口响应信息', allure.attachment_type.TEXT)
                status_code = res.status_code
                # 格式化响应信息记录到 allure（美化显示）
                allure.attach(self.allure_attach_response(res.json()), '接口响应信息', allure.attachment_type.TEXT)

                # ----- 4. 参数提取 + 断言校验 -----
                try:
                    res_json = json.loads(res_text)
                    if extract is not None:
                        self.extract_data(extract, res_text)
                    if extract_lst is not None:
                        self.extract_data_list(extract_lst, res_text)
                    # 处理断言
                    assert_res.assert_result(validation, res_json, status_code)
                except JSONDecodeError as js:
                    logs.error("系统异常或接口未请求！")
                    raise js
                except Exception as e:
                    logs.error(str(traceback.format_exc()))
                    raise e
        except Exception as e:
            logs.error(e)
            raise e

    @classmethod
    def allure_attach_response(cls, response):
        """
        格式化响应信息，用于 allure 测试报告展示

        把字典转成带缩进的 JSON 字符串，让 allure 报告里的响应数据更易读。

        :param response: 接口响应数据，可以是 dict 或 str
        :return: 格式化后的字符串
        """
        if isinstance(response, dict):
            allure_response = json.dumps(response, ensure_ascii=False, indent=4)
        else:
            allure_response = response
        return allure_response

    def extract_data(self, testcase_extract, response):
        r"""
        提取接口的返回参数（单个值），支持正则表达式和 jsonpath 提取

        与 apiutil.py 的 extract_data 区别：
        - 这里的 pattern_lst 用的是 r'(\d+)'（匹配多个数字），是正确的
        - apiutil.py 里写成了 r'(\d)'（只匹配单个数字），有 bug

        :param testcase_extract: testcase 文件 yaml 中的 extract 值（字典）
        :param response: 接口的实际返回值，str 类型
        :return: 无返回值，提取结果直接写入内存业务上下文
        """
        # 正则模式列表，注意这里是 r'(\d+)'（正确版本）
        pattern_lst = ['(.+?)', '(.*?)', r'(\d+)', r'(\d*)']
        try:
            for key, value in testcase_extract.items():
                # ----- 方式一：正则表达式提取（取第一个匹配结果）-----
                for pat in pattern_lst:
                    if pat in value:
                        ext_list = re.search(value, response)
                        if pat in [r'(\d+)', r'(\d*)']:
                            # 数字类型：转成 int 存储
                            extract_date = {key: int(ext_list.group(1))}
                        else:
                            # 字符串类型
                            extract_date = {key: ext_list.group(1)}
                        logs.info('正则提取到的参数：%s' % extract_date)
                        self.read.write_yaml_data(extract_date)
                # ----- 方式二：jsonpath 提取（取第一个）-----
                if "$" in value:
                    ext_json = jsonpath.jsonpath(json.loads(response), value)[0]
                    if ext_json:
                        extract_date = {key: ext_json}
                    else:
                        extract_date = {key: "未提取到数据，该接口返回结果可能为空"}
                    logs.info('json提取到参数：%s' % extract_date)
                    self.read.write_yaml_data(extract_date)
        except:
            logs.error('接口返回值提取异常，请检查yaml文件extract表达式是否正确！')

    def extract_data_list(self, testcase_extract_list, response):
        """
        提取多个参数（列表形式），支持正则表达式和 jsonpath 提取

        与 extract_data 的区别：
        - 正则用 re.findall → 匹配所有结果
        - jsonpath 不用 [0] → 返回整个列表
        - 最终存到 yaml 的是列表

        :param testcase_extract_list: yaml 文件中的 extract_list 信息（字典）
        :param response: 接口的实际返回值，str 类型
        :return: 无返回值，提取结果直接写入内存业务上下文
        """
        try:
            for key, value in testcase_extract_list.items():
                # ----- 方式一：正则表达式提取（取所有匹配项）-----
                if "(.+?)" in value or "(.*?)" in value:
                    # re.findall 匹配所有结果，返回列表
                    # re.S 让 . 也能匹配换行符
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
                        # 提取不到给个默认值，防止后续用例调用时报错
                        extract_date = {key: "未提取到数据，该接口返回结果可能为空"}
                    logs.info('json提取到参数：%s' % extract_date)
                    self.read.write_yaml_data(extract_date)
        except:
            logs.error('接口返回值提取异常，请检查yaml文件extract_list表达式是否正确！')
