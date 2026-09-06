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

from common.auth import AUTH
from common.httpclient import SESSION, HTTP_TIMEOUT
from conf.operationConfig import OperationConfig

API_BASE = OperationConfig().get_section_for_data('api_envi', 'host')
DOC_SAMPLE_GOODS_ID = '18382788819'  # 接口文档示例中的商品ID，作为造数用的已知数据


def _auth_headers():
    return {'token': AUTH.token}


@pytest.fixture(scope='module')
def cart_with_goods():
    """造数前置：把一件商品加入购物车，返回商品ID（供删除购物车用例消费）

    teardown（yield 之后）：无论用例成败都清理购物车。清理幂等——
    商品可能已被用例本身删除（如 test_del_cart_after_add），再次删除返回
    "不存在"或成功均视为清理完成；清理失败仅记录到报告，不掩盖用例本身的结论。
    """
    r = SESSION.post(f'{API_BASE}/coupApply/cms/shoppingJoinCart',
                      json={'goods_id': DOC_SAMPLE_GOODS_ID, 'count': 1, 'price': '1',
                            'timeStamp': int(time.time())},
                      headers=_auth_headers(), timeout=HTTP_TIMEOUT)
    body = r.json()
    assert r.status_code == 200 and body['error_code'] == '0000', f'造数失败，加购未成功：{body}'
    yield DOC_SAMPLE_GOODS_ID
    # teardown：尽力清理，幂等
    try:
        r = SESSION.post(f'{API_BASE}/coupApply/cms/delCart',
                          data={'productId': DOC_SAMPLE_GOODS_ID, 'timeStamp': int(time.time())},
                          headers=_auth_headers(), timeout=HTTP_TIMEOUT)
        cleanup_body = r.json()
        cleaned = r.status_code == 200 and cleanup_body.get('error_code') in ('0000', '4000')
        if not cleaned:
            allure.attach(f'响应: {r.text}', '购物车清理未确认成功', allure.attachment_type.TEXT)
    except Exception as e:
        allure.attach(f'清理异常: {e}', '购物车清理异常', allure.attachment_type.TEXT)


@pytest.fixture(scope='module')
def new_order():
    """造数前置：从商品列表取一件商品提交订单，返回订单号（供订单状态查询用例消费）

    清理限制：接口文档不存在"取消/删除订单"接口，造出的订单无法通过 API 清理，
    依赖 mock 服务无状态兜底；指向真实服务时应改为：调用取消订单接口，
    或使用一次性测试账号/数据库清理任务统一回收。
    """
    r = SESSION.get(f'{API_BASE}/coupApply/cms/goodsList',
                     params={'msgType': 'getHandsetListOfCust', 'page': 1, 'size': 20},
                     headers=_auth_headers(), timeout=HTTP_TIMEOUT)
    goods_list = r.json()['goodsList']
    assert goods_list, '造数失败：商品列表为空'
    r = SESSION.post(f'{API_BASE}/coupApply/cms/placeAnOrder',
                      json={'goods_id': goods_list[0]['goodsId'], 'number': 1,
                            'propertyChildIds': '2:9', 'inviter_id': '127839112',
                            'price': '1', 'freight_insurance': '0.00', 'discount_code': '002399',
                            'consignee_info': {'name': '张三', 'phone': '13800000000',
                                               'address': '北京市海淀区'}},
                      headers=_auth_headers(), timeout=HTTP_TIMEOUT)
    body = r.json()
    assert r.status_code == 200 and body['error_code'] == '0000', f'造数失败，下单未成功：{body}'
    return body['orderNumber']


@allure.feature('单接口·依赖前置数据')
class TestDependentApi:

    @allure.story('删除购物车商品（依赖：购物车中已加购商品）')
    def test_del_cart_after_add(self, cart_with_goods):
        """被测接口：delCart。前置：fixture 已加购商品。断言删除成功。"""
        r = SESSION.post(f'{API_BASE}/coupApply/cms/delCart',
                          data={'productId': cart_with_goods, 'timeStamp': int(time.time())},
                          headers=_auth_headers(), timeout=HTTP_TIMEOUT)
        allure.attach(r.text, 'delCart 响应', allure.attachment_type.TEXT)
        assert r.status_code == 200
        body = r.json()
        assert body['error_code'] == '0000'
        assert body['message'] == 'success'

    @allure.story('校验订单状态（依赖：系统中已有订单）')
    def test_new_order_status(self, new_order):
        """被测接口：checkOrderStatus。前置：fixture 已提交一笔订单。
        文档约定 status 枚举：0已支付/1待支付/2订单关闭；实测新订单返回 '0'。"""
        r = SESSION.post(f'{API_BASE}/coupApply/cms/checkOrderStatus',
                          json={'orderNumber': new_order, 'timeStamp': int(time.time())},
                          headers=_auth_headers(), timeout=HTTP_TIMEOUT)
        allure.attach(f'orderNumber: {new_order}\n响应: {r.text}', '订单状态查询', allure.attachment_type.TEXT)
        assert r.status_code == 200
        body = r.json()
        assert body['error'] == ''
        assert body['status'] == '0'
