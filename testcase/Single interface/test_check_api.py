"""
单接口测试 —— 状态/库存查询类（不依赖其他接口的用例）

覆盖三个查询接口的负向与边界场景：
- checkOrderStatus（校验订单状态）
- checkLogisticsStatus（校验物流状态）
- shoppingInventory（校验库存）
另包含登录接口的参数缺失/空值边界用例（login.yaml）。

所有断言值均来自对 mock 服务真实响应的实测。
"""
import allure
import pytest

from base.apiutil import RequestBase
from base.generateId import m_id, c_id
from common.readyaml import get_testcase_yaml


@allure.feature(next(m_id) + '状态与库存查询（单接口·无依赖）')
class TestCheckApi:

    @allure.story(next(c_id) + "登录边界")
    @pytest.mark.parametrize('base_info,testcase', get_testcase_yaml('./testcase/Single interface/login.yaml'))
    def test_login_edge(self, base_info, testcase):
        allure.dynamic.title(testcase['case_name'])
        RequestBase().specification_yaml(base_info, testcase)

    @allure.story(next(c_id) + "状态与库存查询")
    @pytest.mark.parametrize('case_info', get_testcase_yaml('./testcase/Single interface/checkStatus.yaml'))
    def test_check_status_and_inventory(self, case_info):
        # 每个 case_info 是一个接口文档（baseInfo + testCase 列表），
        # 接口内多条用例（如库存的充足/不足/空ID边界）由链路执行器循环执行
        allure.dynamic.title(case_info['baseInfo']['api_name'])
        RequestBase().specification_yaml_suite(case_info)
