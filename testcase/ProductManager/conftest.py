"""
商品管理套件的造数 fixture。

单接口测试的原则：被测接口依赖的"前置数据"由 fixture 造出来并通过返回值交给用例，
用例之间零依赖——任何一条用例都可以单独运行、乱序运行。

fixture 内部复用套件里的 YAML 用例作为造数脚本（跑 getProductList / commitOrder），
提取值经由内存业务上下文（common/context.py）在步骤间传递属于实现细节，
对测试暴露的只有 fixture 的返回值。
"""
import copy

import pytest

from base.apiutil import RequestBase
from common.readyaml import ReadYamlData, get_testcase_yaml

YAML_DIR = './testcase/ProductManager'


@pytest.fixture(scope='module')
def product_goods_id():
    """造数前置：调商品列表接口，返回一个可用商品ID"""
    base_info, test_case = get_testcase_yaml(f'{YAML_DIR}/getProductList.yaml')[0]
    RequestBase().specification_yaml(base_info, test_case)
    goods_ids = ReadYamlData().get_extract_yaml('goodsId')
    assert goods_ids, '商品列表未提取到 goodsId，无法为后续用例造数'
    return goods_ids[0]


@pytest.fixture(scope='module')
def order_data(product_goods_id):
    """造数前置：用商品ID提交一笔订单，返回 {'orderNumber': ..., 'userId': ...}"""
    base_info, test_case = get_testcase_yaml(f'{YAML_DIR}/commitOrder.yaml')[0]
    test_case = copy.deepcopy(test_case)
    test_case['json']['goods_id'] = product_goods_id
    RequestBase().specification_yaml(base_info, test_case)
    read = ReadYamlData()
    order_data = {
        'orderNumber': read.get_extract_yaml('orderNumber'),
        'userId': read.get_extract_yaml('userId'),
    }
    assert all(order_data.values()), f'提交订单未提取到 orderNumber/userId：{order_data}'
    return order_data
