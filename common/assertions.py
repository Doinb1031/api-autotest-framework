import traceback
import allure
import jsonpath
import operator

from common.recordlog import logs
from common.connection import ConnectMysql


class Assertions:
    """
    接口断言模式，支持
    1)响应文本字符串包含模式断言 contains
    2)响应结果相等断言 eq
    3)响应结果不相等断言 ne
    4)响应结果任意值断言 rv
    5)数据库断言 db
    6)字段存在性断言 exists（jsonpath 表达式能否取到值）

    所有断言方法均返回 flag 标识：0 表示通过，非 0 表示失败。
    由 assert_result() 统一调度，根据 YAML 文件中 validation 的关键字段选择对应断言方式。
    """

    def contains_assert(self, value, response, status_code):
        """
        字符串包含断言模式，断言预期结果的字符串是否包含在接口的响应信息中。

        :param value: 预期结果,dict 格式,如 {'msg': '调用成功', 'status_code': 200}
        :param response: 接口实际响应结果(dict 或 JSON 字符串)
        :param status_code: 响应状态码(int)
        :return: int,0 表示通过，非 0 表示失败
        """
        # 断言状态标识，0成功，其他失败
        flag = 0
        # 遍历预期结果的每个键值对
        for assert_key, assert_value in value.items():
            if assert_key == "status_code":
                # 特殊处理：断言 HTTP 状态码
                if assert_value != status_code:
                    flag += 1
                    allure.attach(f"预期结果：{assert_value}\n实际结果:{status_code}", '响应代码断言结果:失败',
                                  attachment_type=allure.attachment_type.TEXT)
                    logs.error("contains断言失败:接口返回码【%s】不等于【%s】" % (status_code, assert_value))
            else:
                # 使用 jsonpath 递归查找响应中所有匹配 assert_key 的值
                resp_list = jsonpath.jsonpath(response, "$..%s" % assert_key)
                # 将所有匹配值统一转为字符串后拼接，做子串包含判断
                resp_list = ''.join(str(item) for item in resp_list)
                if resp_list:
                    # 'NONE' 字符串特殊处理为 'None'（与 str(None) 拼接结果匹配，用于断言字段为空）
                    assert_value = 'None' if assert_value.upper() == 'NONE' else assert_value
                    # 检查预期值是否包含在实际结果中
                    if assert_value in resp_list:
                        logs.info("字符串包含断言成功：预期结果【%s】,实际结果【%s】" % (assert_value, resp_list))
                    else:
                        flag = flag + 1
                        allure.attach(f"预期结果：{assert_value}\n实际结果：{resp_list}", '响应文本断言结果：失败',
                                      attachment_type=allure.attachment_type.TEXT)
                        logs.error("响应文本断言失败：预期结果为【%s】,实际结果为【%s】" % (assert_value, resp_list))
                else:
                    # 字段在响应中不存在时本断言未生效（空过），必须告警提示用例作者排查
                    logs.warning("contains断言：响应中未找到字段【%s】，本断言未生效（空过），请确认断言是否写错字段名" % assert_key)
        return flag

    def exists_assert(self, value, response):
        """
        字段存在性断言模式：用 jsonpath 表达式判断响应中能否取到值。

        用于守住"列表非空""关键字段必须在"这类约束，弥补 contains 在字段缺失时
        静默通过的空过缺陷（如 goodsList 为空时 goodsId 提取空列表）。

        :param value: 预期结果，dict 格式，key 为 jsonpath 表达式，value 为布尔，
                      如 {'$.goodsList[0]': True} 表示取得到值、{'$.error.field': False} 表示取不到
        :param response: 接口实际响应结果(dict)
        :return: int,0 表示通过，非 0 表示失败
        """
        flag = 0
        for expr, expected in value.items():
            found = jsonpath.jsonpath(response, expr)
            actual = bool(found)
            if actual != bool(expected):
                flag = flag + 1
                allure.attach(f"jsonpath表达式：{expr}\n预期：{'存在' if expected else '不存在'}\n实际：{'存在' if actual else '不存在'}",
                              '存在性断言结果：失败', attachment_type=allure.attachment_type.TEXT)
                logs.error("存在性断言失败：表达式【%s】预期%s，实际%s" % (
                    expr, '存在' if expected else '不存在', '存在' if actual else '不存在'))
            else:
                logs.info("存在性断言成功：表达式【%s】，预期%s与实际一致" % (expr, '存在' if expected else '不存在'))
        return flag

    def equal_assert(self, expected_results, actual_results, status_code=None):
        """
        相等断言模式：检查实际结果中指定字段的值是否等于预期值，支持多个字段整体比较。

        :param expected_results: 预期结果,dict 格式，支持多字段，如 {'code': 0, 'msg': '成功'}
        :param actual_results: 接口实际响应结果,dict 格式
        :param status_code: 保留参数，未使用
        :return: int,0 表示通过，非 0 表示失败
        """
        flag = 0
        if isinstance(actual_results, dict) and isinstance(expected_results, dict):
            # 校验预期结果的每个 key 是否都能在实际结果中找到，避免取值时抛异常
            missing_keys = set(expected_results.keys()) - set(actual_results.keys())
            if missing_keys:
                flag += 1
                logs.error(f"相等断言失败：实际结果中缺少预期字段{missing_keys}，实际结果为：{actual_results}")
                allure.attach(f"预期结果：{str(expected_results)}\n实际结果缺少字段：{missing_keys}", '相等断言结果：失败',
                              attachment_type=allure.attachment_type.TEXT)
                return flag
            # 按预期结果的全部 key 从实际结果中提取对应字段，重新生成比较字典
            new_actual_results = {key: actual_results[key] for key in expected_results.keys()}
            # 使用 operator.eq 比较两个字典是否完全相等
            eq_assert = operator.eq(new_actual_results, expected_results)
            if eq_assert:
                logs.info(f"相等断言成功：接口实际结果：{new_actual_results}，等于预期结果：" + str(expected_results))
                allure.attach(f"预期结果：{str(expected_results)}\n实际结果：{new_actual_results}", '相等断言结果：成功',
                              attachment_type=allure.attachment_type.TEXT)
            else:
                flag += 1
                logs.error(f"相等断言失败：接口实际结果{new_actual_results}，不等于预期结果：" + str(expected_results))
                allure.attach(f"预期结果：{str(expected_results)}\n实际结果：{new_actual_results}", '相等断言结果：失败',
                              attachment_type=allure.attachment_type.TEXT)
        else:
            raise TypeError('相等断言--类型错误，预期结果和接口实际响应结果必须为字典类型！')
        return flag

    def not_equal_assert(self, expected_results, actual_results, status_code=None):
        """
        不相等断言模式：检查实际结果中指定字段的值是否不等于预期值，支持多个字段整体比较。

        :param expected_results: 预期结果，dict 格式，支持多字段，如 {'code': 0, 'msg': '成功'}
        :param actual_results: 接口实际响应结果，dict 格式
        :param status_code: 保留参数，未使用
        :return: int，0 表示通过，非 0 表示失败
        """
        flag = 0
        if isinstance(actual_results, dict) and isinstance(expected_results, dict):
            # 校验预期结果的每个 key 是否都能在实际结果中找到，避免取值时抛异常
            missing_keys = set(expected_results.keys()) - set(actual_results.keys())
            if missing_keys:
                flag += 1
                logs.error(f"不相等断言失败：实际结果中缺少预期字段{missing_keys}，实际结果为：{actual_results}")
                allure.attach(f"预期结果：{str(expected_results)}\n实际结果缺少字段：{missing_keys}", '不相等断言结果：失败',
                              attachment_type=allure.attachment_type.TEXT)
                return flag
            # 按预期结果的全部 key 从实际结果中提取对应字段，重新生成比较字典
            new_actual_results = {key: actual_results[key] for key in expected_results.keys()}
            # 使用 operator.ne 比较两个字典是否不相等
            eq_assert = operator.ne(new_actual_results, expected_results)
            if eq_assert:
                logs.info(f"不相等断言成功：接口实际结果：{new_actual_results}，不等于预期结果：" + str(expected_results))
                allure.attach(f"预期结果：{str(expected_results)}\n实际结果：{new_actual_results}", '不相等断言结果：成功',
                              attachment_type=allure.attachment_type.TEXT)
            else:
                flag += 1
                logs.error(f"不相等断言失败：接口实际结果{new_actual_results}，等于预期结果：" + str(expected_results))
                allure.attach(f"预期结果：{str(expected_results)}\n实际结果：{new_actual_results}", '不相等断言结果：失败',
                              attachment_type=allure.attachment_type.TEXT)
        else:
            raise TypeError('不相等断言--类型错误，预期结果和接口实际响应结果必须为字典类型！')
        return flag

    def assert_response_any(self, actual_results, expected_results):
        """
        断言接口响应信息中任意属性值是否与预期值匹配。
        与 equal_assert 类似，但直接从实际结果的顶层 key 中查找。

        :param actual_results: 接口实际响应信息，dict 格式
        :param expected_results: 预期结果，dict 格式，如 {'code': 0}
        :return: int，0 表示通过，非 0 表示失败
        """
        flag = 0
        try:
            # 取预期结果的第一个 key
            exp_key = list(expected_results.keys())[0]
            if exp_key in actual_results:
                # 从实际结果中取出该 key 对应的值
                act_value = actual_results[exp_key]
                # 与预期值比较是否相等
                rv_assert = operator.eq(act_value, list(expected_results.values())[0])
                if rv_assert:
                    logs.info("响应结果任意值断言成功")
                else:
                    flag += 1
                    logs.error("响应结果任意值断言失败")
        except Exception as e:
            logs.error(e)
            raise
        return flag

    def assert_response_time(self, res_time, exp_time):
        """
        响应时间断言：接口响应时间小于预期时间则通过。

        :param res_time: 接口的实际响应时间（秒）
        :param exp_time: 预期的最大响应时间（秒）
        :return: True 表示通过；失败则抛出 AssertionError
        """
        try:
            assert res_time < exp_time
            return True
        except Exception as e:
            logs.error('接口响应时间[%ss]大于预期时间[%ss]' % (res_time, exp_time))
            raise

    def assert_mysql_data(self, expected_results):
        """
        数据库断言：执行 SQL 查询，验证数据库中是否存在对应数据。

        :param expected_results: 预期结果，这里传入的是 SQL 查询语句字符串
        :return: int，0 表示通过，非 0 表示失败
        """
        flag = 0
        conn = ConnectMysql()
        # 执行 SQL 查询，返回查询结果
        db_value = conn.query_all(expected_results)
        if db_value is not None:
            logs.info("数据库断言成功")
        else:
            flag += 1
            logs.error("数据库断言失败，请检查数据库是否存在该数据！")
        return flag

    def assert_result(self, expected, response, status_code):
        """
        断言入口方法：根据 YAML 文件 validation 中定义的断言类型，分发给对应的具体断言方法。
        通过累加 all_flag 判断整体测试结果:0 表示全部通过，非 0 表示有失败项。

        :param expected: 预期结果,list 格式，每个元素是一个 dict,如 [{'contains': {'msg': '成功'}}]
        :param response: 实际响应结果(dict)
        :param status_code: 响应状态码(int)
        :return: None,通过 assert True/False 决定测试用例通过或失败
        """

        # 0, 表示全部通过，>0 有all_flag个失败项
        all_flag = 0
        try:
            logs.info("yaml文件预期结果:%s" % expected)
            # 遍历预期结果列表，每项是一个断言配置字典
            for yq in expected:
                for key, value in yq.items():
                    # 根据 key 选择对应的断言方式
                    if key == "contains":
                        # 字符串包含断言
                        flag = self.contains_assert(value, response, status_code)
                        all_flag = all_flag + flag
                    elif key == "eq":
                        # 相等断言
                        flag = self.equal_assert(value, response)
                        all_flag = all_flag + flag
                    elif key == 'ne':
                        # 不相等断言
                        flag = self.not_equal_assert(value, response)
                        all_flag = all_flag + flag
                    elif key == 'rv':
                        # 任意值断言
                        flag = self.assert_response_any(actual_results=response, expected_results=value)
                        all_flag = all_flag + flag
                    elif key == 'db':
                        # 数据库断言
                        flag = self.assert_mysql_data(value)
                        all_flag = all_flag + flag
                    elif key == 'exists':
                        # 字段存在性断言（jsonpath 表达式）
                        flag = self.exists_assert(value, response)
                        all_flag = all_flag + flag
                    else:
                        logs.error("不支持此种断言方式")

        except Exception as exceptions:
            logs.error('接口断言异常,请检查yaml预期结果值是否正确填写!')
            raise exceptions

        # 根据累加的 flag 判断最终结果
        if all_flag == 0:
            logs.info("测试成功")
            assert True
        else:
            logs.error("测试失败")
            assert False
