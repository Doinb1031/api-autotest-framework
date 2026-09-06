import allure
import pytest

from common.readyaml import get_testcase_yaml
from base.apiutil import RequestBase
from base.generateId import m_id, c_id


# 业务场景链路用例调用 base/apiutil.py 的多用例入口 specification_yaml_suite

@allure.feature(next(m_id) + '电子商务管理系统（业务场景）')
class TestEBusinessScenario:

    @allure.story(next(c_id) + '商品列表到下单支付流程')
    @pytest.mark.parametrize('case_info', get_testcase_yaml('./testcase/Business interface/BusinessScenario.yml'))
    def test_business_scenario(self, case_info):
        allure.dynamic.title(case_info['baseInfo']['api_name'])
        RequestBase().specification_yaml_suite(case_info)
