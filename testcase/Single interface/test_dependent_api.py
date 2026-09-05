"""
单接口测试 —— 依赖其他接口数据的用例（fixture 造数模式）

被测接口自身是测试目标，它依赖的前置数据（购物车里有商品、系统里有订单）
由 fixture 调上游接口造出来，并通过返回值注入用例。
用例之间零依赖：可单独运行、乱序运行。

与 YAML 数据驱动用例的区别：这类用例的前置数据需要"造出来再传进来"，
pytest 原生写法（fixture + 直接断言）比绕道全局变量更清晰。
"""
import time

import allure
import pytest
import requests

from common.auth import AUTH
from conf.operationConfig import OperationConfig

API_BASE = OperationConfig().get_section_for_data('api_envi', 'host')
DOC_SAMPLE_GOODS_ID = '18382788819'  # 接口文档示例中的商品ID，作为造数用的已知数据


def _auth_headers():
    return {'token': AUTH.token}


@pytest.fixture(scope='module')
def cart_with_goods():
    """造数前置：把一件商品加入购物车，返回商品ID（供删除购物车用例消费）"""
    r = requests.post(f'{API_BASE}/coupApply/cms/shoppingJoinCart',
                      json={'goods_id': DOC_SAMPLE_GOODS_ID, 'count': 1, 'price': '1',
                            'timeStamp': int(time.time())},
                      headers=_auth_headers(), verify=False, timeout=60)
    body = r.json()
    assert r.status_code == 200 and body['error_code'] == '0000', f'造数失败，加购未成功：{body}'
    return DOC_SAMPLE_GOODS_ID


@pytest.fixture(scope='module')
def new_order():
    """造数前置：从商品列表取一件商品提交订单，返回订单号（供订单状态查询用例消费）"""
    r = requests.get(f'{API_BASE}/coupApply/cms/goodsList',
                     params={'msgType': 'getHandsetListOfCust', 'page': 1, 'size': 20},
                     headers=_auth_headers(), verify=False, timeout=60)
    goods_list = r.json()['goodsList']
    assert goods_list, '造数失败：商品列表为空'
    r = requests.post(f'{API_BASE}/coupApply/cms/placeAnOrder',
                      json={'goods_id': goods_list[0]['goodsId'], 'number': 1,
                            'propertyChildIds': '2:9', 'inviter_id': '127839112',
                            'price': '1', 'freight_insurance': '0.00', 'discount_code': '002399',
                            'consignee_info': {'name': '张三', 'phone': '13800000000',
                                               'address': '北京市海淀区'}},
                      headers=_auth_headers(), verify=False, timeout=60)
    body = r.json()
    assert r.status_code == 200 and body['error_code'] == '0000', f'造数失败，下单未成功：{body}'
    return body['orderNumber']


@allure.feature('单接口·依赖前置数据')
class TestDependentApi:

    @allure.story('删除购物车商品（依赖：购物车中已加购商品）')
    def test_del_cart_after_add(self, cart_with_goods):
        """被测接口：delCart。前置：fixture 已加购商品。断言删除成功。"""
        r = requests.post(f'{API_BASE}/coupApply/cms/delCart',
                          data={'productId': cart_with_goods, 'timeStamp': int(time.time())},
                          headers=_auth_headers(), verify=False, timeout=60)
        allure.attach(r.text, 'delCart 响应', allure.attachment_type.TEXT)
        assert r.status_code == 200
        body = r.json()
        assert body['error_code'] == '0000'
        assert body['message'] == 'success'

    @allure.story('校验订单状态（依赖：系统中已有订单）')
    def test_new_order_status(self, new_order):
        """被测接口：checkOrderStatus。前置：fixture 已提交一笔订单。
        文档约定 status 枚举：0已支付/1待支付/2订单关闭；实测新订单返回 '0'。"""
        r = requests.post(f'{API_BASE}/coupApply/cms/checkOrderStatus',
                          json={'orderNumber': new_order, 'timeStamp': int(time.time())},
                          headers=_auth_headers(), verify=False, timeout=60)
        allure.attach(f'orderNumber: {new_order}\n响应: {r.text}', '订单状态查询', allure.attachment_type.TEXT)
        assert r.status_code == 200
        body = r.json()
        assert body['error'] == ''
        assert body['status'] == '0'
