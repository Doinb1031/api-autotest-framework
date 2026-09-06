"""
单接口测试文件 —— 用户管理模块

本文件对"用户管理"的 4 个单接口进行测试：新增、修改、删除、查询。
每个接口的测试数据写在对应的 YAML 文件中，通过数据驱动方式执行。

用例之间零依赖：可单独运行、乱序运行，无 @pytest.mark.run 顺序标记。
正向用例的数据来源分两类（见各 YAML 内注释）：
- 新增：用户名带时间戳唯一化，每次执行都幂等；
- 修改/删除/查询：使用 mock 服务的种子用户数据（无状态 mock 不认运行期新增的用户，
  且新增接口不返回 user_id，无法在 mock 上构造真实的增改查链路）。
"""
import allure
import pytest

# get_testcase_yaml：读取 YAML 测试用例文件，返回 [baseInfo, testCase] 配对列表
from common.readyaml import get_testcase_yaml
# RequestBase：接口请求核心类，负责组装并发送请求、提取参数、断言校验
from base.apiutil import RequestBase
# m_id / c_id：生成器和编号，给 allure 报告的模块和用例编号
from base.generateId import m_id, c_id


# @allure.feature：allure 报告的一级分类（模块），显示为 "M01_用户管理模块（单接口）"
@allure.feature(next(m_id) + '用户管理模块（单接口）')
class TestUserManager:

    # @allure.story：allure 报告的二级分类（场景），显示为 "C01_新增用户"
    @allure.story(next(c_id) + "新增用户")
    # @pytest.mark.parametrize：数据驱动，读取 addUser.yaml 的每组测试数据
    # base_info：接口基础信息（url、method、header 等）
    # testcase：测试数据（参数、断言、提取等），每组数据会生成一个独立的测试用例
    @pytest.mark.parametrize('base_info,testcase', get_testcase_yaml("./testcase/Single interface/addUser.yaml"))
    def test_add_user(self, base_info, testcase):
        # 用 case_name 作为 allure 报告中的用例标题（动态标题）
        allure.dynamic.title(testcase['case_name'])
        # 执行接口请求：拼接 URL → 替换 ${} 占位符 → 发送请求 → 断言 → 提取参数
        RequestBase().specification_yaml(base_info, testcase)

    @allure.story(next(c_id) + "修改用户")
    @pytest.mark.parametrize('base_info,testcase', get_testcase_yaml("./testcase/Single interface/updateUser.yaml"))
    def test_update_user(self, base_info, testcase):
        allure.dynamic.title(testcase['case_name'])
        RequestBase().specification_yaml(base_info, testcase)

    @allure.story(next(c_id) + "删除用户")
    @pytest.mark.parametrize('base_info,testcase', get_testcase_yaml("./testcase/Single interface/deleteUser.yaml"))
    def test_delete_user(self, base_info, testcase):
        allure.dynamic.title(testcase['case_name'])
        RequestBase().specification_yaml(base_info, testcase)

    @allure.story(next(c_id) + "查询用户")
    @pytest.mark.parametrize('base_info,testcase', get_testcase_yaml("./testcase/Single interface/queryUser.yaml"))
    def test_query_user(self, base_info, testcase):
        allure.dynamic.title(testcase['case_name'])
        RequestBase().specification_yaml(base_info, testcase)
