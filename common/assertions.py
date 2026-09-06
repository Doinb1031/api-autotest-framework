"""
接口断言模块，支持六种断言方式（YAML validation 里的 key）：
1) contains：响应中指定字段的值包含预期子串（status_code 特判 HTTP 状态码）
2) eq       ：响应中指定字段等于预期值
3) ne       ：响应中指定字段不等于预期值
4) rv       ：任意值断言（顶层字段等于预期值）
5) db       ：数据库断言（执行 SQL，结果非空即通过）
6) exists   ：字段存在性断言（jsonpath 表达式能否取到值）

设计约定（真实企业实践的断言纪律）：
- 每条断言的失败都生成"哪条断言、期望什么、实际什么"的详情字符串；
- assert_result 把所有失败详情聚合后以 AssertionError 抛出，
  pytest 报告里直接可见失败原因，不需要再翻日志；
- 不存在"静默通过"：字段缺失、断言类型写错都按失败处理。
"""
import allure
import jsonpath
import operator

from common.recordlog import logs
from common.connection import ConnectMysql

# 支持的断言类型，用于给写错类型的用例明确报错
SUPPORTED_ASSERT_KEYS = ('contains', 'eq', 'ne', 'rv', 'db', 'exists')


class Assertions:
    """断言执行器。各断言方法返回失败详情列表（空列表 = 全部通过）。"""

    def _fail(self, message, expected, actual):
        """统一生成一条失败详情：记录日志 + 附加 allure + 返回详情字符串。"""
        detail = f"{message}；预期【{expected}】，实际【{actual}】"
        logs.error(detail)
        allure.attach(f"预期：{expected}\n实际：{actual}", message, allure.attachment_type.TEXT)
        return detail

    def contains_assert(self, value, response, status_code):
        """
        字符串包含断言：响应中指定字段的值（jsonpath $..key 递归查找所有匹配），
        任意一个匹配值包含预期子串即通过。

        :param value: 预期结果，dict 格式，如 {'msg': '成功', 'status_code': 200}
        :param response: 接口实际响应结果(dict)
        :param status_code: 响应状态码(int)
        :return: 失败详情列表，空列表表示通过
        """
        failures = []
        for assert_key, assert_value in value.items():
            if assert_key == "status_code":
                # 特殊处理：断言 HTTP 状态码
                if assert_value != status_code:
                    failures.append(self._fail(
                        f"contains断言失败：HTTP状态码不符", assert_value, status_code))
                else:
                    logs.info("contains断言成功：status_code=%s" % status_code)
            else:
                # jsonpath 递归查找响应中所有匹配 assert_key 的值
                resp_list = jsonpath.jsonpath(response, "$..%s" % assert_key)
                if not resp_list:
                    # 字段缺失按失败处理。此前的"空过"会掩盖断言写错字段名的问题，
                    # 让用例在没有真正校验任何内容的情况下显示通过（假绿）。
                    failures.append(self._fail(
                        f"contains断言失败：响应中不存在字段【{assert_key}】", assert_value, '字段不存在'))
                    continue
                expected_str = str(assert_value)
                # 'NONE' 字符串特殊处理为 'None'（与 str(None) 一致，用于断言字段为空）
                if expected_str.upper() == 'NONE':
                    expected_str = 'None'
                # 逐个匹配值判断包含关系，避免把多个字段值拼接后产生的跨字段误匹配
                matched = any(expected_str in str(item) for item in resp_list)
                if matched:
                    logs.info("contains断言成功：字段【%s】包含预期【%s】" % (assert_key, expected_str))
                else:
                    failures.append(self._fail(
                        f"contains断言失败：字段【{assert_key}】的值不包含预期", expected_str, resp_list))
        return failures

    def exists_assert(self, value, response):
        """
        字段存在性断言：用 jsonpath 表达式判断响应中能否取到值。

        用于守住"列表非空""关键字段必须在"这类约束。

        :param value: 预期结果，dict 格式，key 为 jsonpath 表达式，value 为布尔，
                      如 {'$.goodsList[0]': True} 表示取得到值、{'$.error.field': False} 表示取不到
        :param response: 接口实际响应结果(dict)
        :return: 失败详情列表，空列表表示通过
        """
        failures = []
        for expr, expected in value.items():
            found = jsonpath.jsonpath(response, expr)
            actual = bool(found)
            if actual != bool(expected):
                failures.append(self._fail(
                    f"exists断言失败：表达式【{expr}】",
                    '存在' if expected else '不存在', '存在' if actual else '不存在'))
            else:
                logs.info("exists断言成功：表达式【%s】预期%s与实际一致" % (
                    expr, '存在' if expected else '不存在'))
        return failures

    def equal_assert(self, expected_results, actual_results):
        """
        相等断言：实际结果中预期指定的字段，值必须整体相等（支持多字段）。

        :param expected_results: 预期结果，dict 格式，如 {'code': 0, 'msg': '成功'}
        :param actual_results: 接口实际响应结果，dict 格式
        :return: 失败详情列表，空列表表示通过
        """
        failures = []
        if not (isinstance(actual_results, dict) and isinstance(expected_results, dict)):
            failures.append(self._fail(
                "eq断言失败：预期结果和实际响应必须是字典类型", expected_results, actual_results))
            return failures
        # 校验预期结果的每个 key 是否都能在实际结果中找到，避免取值时抛异常
        missing_keys = set(expected_results.keys()) - set(actual_results.keys())
        if missing_keys:
            failures.append(self._fail(
                f"eq断言失败：实际响应中缺少预期字段{sorted(missing_keys)}", expected_results, actual_results))
            return failures
        new_actual = {key: actual_results[key] for key in expected_results.keys()}
        if operator.eq(new_actual, expected_results):
            logs.info(f"eq断言成功：{new_actual} 等于预期 {expected_results}")
            allure.attach(f"预期：{expected_results}\n实际：{new_actual}", 'eq断言成功',
                          allure.attachment_type.TEXT)
        else:
            # 逐字段给出差异，方便直接定位是哪个字段不符
            diff = {k: {'预期': v, '实际': new_actual[k]}
                    for k, v in expected_results.items() if new_actual[k] != v}
            failures.append(self._fail("eq断言失败：字段值不符", expected_results, diff))
        return failures

    def not_equal_assert(self, expected_results, actual_results):
        """
        不相等断言：实际结果中预期指定的字段，值必须不全等（支持多字段）。

        :param expected_results: 预期结果，dict 格式
        :param actual_results: 接口实际响应结果，dict 格式
        :return: 失败详情列表，空列表表示通过
        """
        failures = []
        if not (isinstance(actual_results, dict) and isinstance(expected_results, dict)):
            failures.append(self._fail(
                "ne断言失败：预期结果和实际响应必须是字典类型", expected_results, actual_results))
            return failures
        missing_keys = set(expected_results.keys()) - set(actual_results.keys())
        if missing_keys:
            failures.append(self._fail(
                f"ne断言失败：实际响应中缺少预期字段{sorted(missing_keys)}", expected_results, actual_results))
            return failures
        new_actual = {key: actual_results[key] for key in expected_results.keys()}
        if operator.ne(new_actual, expected_results):
            logs.info(f"ne断言成功：{new_actual} 不等于预期 {expected_results}")
        else:
            failures.append(self._fail("ne断言失败：实际值等于被排除的预期值", expected_results, new_actual))
        return failures

    def assert_response_any(self, actual_results, expected_results):
        """
        rv 任意值断言：实际结果顶层字段与预期值相等。校验预期里的全部 key。

        :param actual_results: 接口实际响应信息，dict 格式
        :param expected_results: 预期结果，dict 格式，如 {'code': 0}
        :return: 失败详情列表，空列表表示通过
        """
        failures = []
        for exp_key, exp_value in expected_results.items():
            if exp_key not in actual_results:
                failures.append(self._fail(
                    f"rv断言失败：响应中不存在字段【{exp_key}】", exp_value, '字段不存在'))
                continue
            if operator.eq(actual_results[exp_key], exp_value):
                logs.info("rv断言成功：字段【%s】等于预期【%s】" % (exp_key, exp_value))
            else:
                failures.append(self._fail(
                    f"rv断言失败：字段【{exp_key}】值不符", exp_value, actual_results[exp_key]))
        return failures

    def assert_response_time(self, res_time, exp_time):
        """
        响应时间断言：接口响应时间小于预期时间则通过。

        :param res_time: 接口的实际响应时间（秒）
        :param exp_time: 预期的最大响应时间（秒）
        :return: True 表示通过；失败则抛出 AssertionError
        """
        if res_time < exp_time:
            logs.info('接口响应时间[%ss]小于预期时间[%ss]' % (res_time, exp_time))
            return True
        raise AssertionError('接口响应时间[%ss]大于预期时间[%ss]' % (res_time, exp_time))

    def assert_mysql_data(self, expected_results):
        """
        数据库断言：执行 SQL 查询，验证数据库中能查到数据。

        :param expected_results: 预期结果，这里传入的是 SQL 查询语句字符串
        :return: 失败详情列表，空列表表示通过
        """
        conn = ConnectMysql()
        db_value = conn.query_all(expected_results)
        if db_value:
            logs.info("数据库断言成功")
            return []
        return [self._fail("db断言失败：数据库中未查到数据", expected_results, '查询结果为空')]

    def assert_result(self, expected, response, status_code):
        """
        断言入口：根据 YAML validation 里定义的断言类型分发给具体断言方法，
        聚合全部失败详情，有任何失败则以带详情的 AssertionError 结束用例。

        :param expected: 预期结果，list 格式，每个元素是一个 dict，如 [{'contains': {'msg': '成功'}}]
        :param response: 实际响应结果(dict)
        :param status_code: 响应状态码(int)
        :return: None；有失败项时抛出 AssertionError（详情即 pytest 报告中的失败原因）
        """
        failures = []
        try:
            logs.info("yaml文件预期结果:%s" % expected)
            for yq in expected:
                for key, value in yq.items():
                    if key == "contains":
                        failures += self.contains_assert(value, response, status_code)
                    elif key == "eq":
                        failures += self.equal_assert(value, response)
                    elif key == 'ne':
                        failures += self.not_equal_assert(value, response)
                    elif key == 'rv':
                        failures += self.assert_response_any(response, value)
                    elif key == 'db':
                        failures += self.assert_mysql_data(value)
                    elif key == 'exists':
                        failures += self.exists_assert(value, response)
                    else:
                        # 断言类型写错按失败处理（此前只记日志，用例会静默通过）
                        failures.append(self._fail(
                            "断言类型不支持",
                            f"应为 {SUPPORTED_ASSERT_KEYS} 之一", key))
        except Exception as exceptions:
            logs.error('接口断言执行异常,请检查yaml预期结果值是否正确填写!')
            raise exceptions

        if failures:
            summary = f"共 {len(failures)} 项断言失败：\n" + "\n".join(
                f"{i}. {msg}" for i, msg in enumerate(failures, start=1))
            logs.error(summary)
            allure.attach(summary, '断言失败详情', allure.attachment_type.TEXT)
            raise AssertionError(summary)
        logs.info("测试成功：全部断言通过")
