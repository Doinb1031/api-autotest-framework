import pytest
import allure
from common.readyaml import ReadYamlData, get_testcase_yaml
from base.apiutil import RequestBase
from common.auth import AUTH
from common.recordlog import logs
from common.connection import ConnectMysql

"""
-function：每一个函数或方法都会调用
-class：每一个类调用一次，一个类中可以有多个方法
-module：每一个.py文件调用一次，该文件内又有多个function和class
-session：是多个文件调用一次，可以跨.py文件调用，每个.py文件就是module,整个会话只会运行一次
- autouse：默认为false，不会自动执行，需要手动调用，为true可以自动执行，不需要调用
- yield：前置、后置
"""

yfd = ReadYamlData()


@pytest.fixture(autouse=True)
def start_test_and_end():
    logs.info('-------------接口测试开始--------------')
    yield
    logs.info('-------------接口测试结束--------------')


@pytest.fixture(scope='session', autouse=True)
@allure.story("登录")
def system_login():
    # 清空 extract.yaml，避免上次运行的业务数据残留影响本次测试
    # 登录态（token/Cookie）由 auth 模块保存在内存，不落盘
    yfd.clear_yaml_data()
    try:
        body = AUTH.login()
        assert body.get('msg') == '登录成功', '登录接口返回异常：%s' % body
    except Exception as e:
        logs.error(f'登录接口出现异常，导致后续接口无法继续运行，请检查程序！，{e}')
        pytest.fail('登录失败，后续接口无法执行：%s' % e)


@pytest.fixture(scope='session', autouse=True)
def datadb_init():
    """
    后置处理器，比如测试之后的数据清理
    数据库可以预先预置一批本次测试的数据，在测试完成之后将这批数据清理，就不会对系统造成影响，也不会产生脏数据
    :return:
    """
    # conn = ConnectMysql()
    # yield
    # sql = "delete from sys_user where login_name='test999'"
    # conn.delete(sql)
    # allure.attach('将测试数据清空', 'fixture后置', allure.attachment_type.TEXT)

    pass


@pytest.fixture(scope='module')
def order_pay_precondition():
    """
    订单支付用例前置：单独调试时自动补齐“商品列表->提交订单”上游链，保证 extract.yaml 中有 orderNumber/userId 可供引用。

    全量运行时，order=3 的提交订单用例已先执行并写入 extract.yaml，此处检测到已有值则跳过，避免重复下单产生脏数据；
    单独运行 orderPay 用例时，extract.yaml 初始只有登录写入的 token，需要先把上游接口补齐后才能取到订单号。
    :return:
    """
    read = ReadYamlData()
    if read.get_extract_yaml('orderNumber') is None:
        for yaml_path in ['./testcase/ProductManager/getProductList.yaml',
                          './testcase/ProductManager/commitOrder.yaml']:
            base_info, test_case = get_testcase_yaml(yaml_path)[0]
            RequestBase().specification_yaml(base_info, test_case)
