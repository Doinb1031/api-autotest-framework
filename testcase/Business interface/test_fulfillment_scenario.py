"""
业务流程测试 —— 电商履约查询流程（商品列表 → 加购 → 下单 → 支付 → 订单状态 → 物流状态 → 清理）

与 test_business_scenario.py（下单支付链路）互补：
本链路延伸到"支付后的履约查询"——订单状态与物流状态必须能查到刚支付的订单，
并在末尾清理购物车数据。数据经内存业务上下文沿链路传递。
"""
import allure
import pytest

from common.readyaml import get_testcase_yaml
from base.apiutil import RequestBase
from base.generateId import m_id, c_id

# 核心业务链路冒烟集成员
pytestmark = [pytest.mark.smoke]


@allure.feature(next(m_id) + '电子商务管理系统（履约查询流程）')
class TestFulfillmentScenario:

    @allure.story(next(c_id) + '下单支付后订单与物流状态可查')
    @pytest.mark.parametrize('case_info', get_testcase_yaml('./testcase/Business interface/FulfillmentScenario.yml'))
    def test_fulfillment_scenario(self, case_info):
        allure.dynamic.title(case_info['baseInfo']['api_name'])
        RequestBase().specification_yaml_suite(case_info)
