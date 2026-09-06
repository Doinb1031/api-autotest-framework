"""
单接口负向用例（pytest 原生）

承接自 Business interface 下从未被执行过的孤儿 YAML（test_07/test_09/test_10）。
孤儿文件的问题是断言与 mock 实际契约不符：写的期望是 'msg: 失败'、'订单支付失败'、
甚至删除不存在商品仍期望成功码 '0000'；实测 mock 对这三个负向场景统一返回
HTTP 200 + error_code '4000' 的结构化错误（与 checkOrderStatus 的负向契约一致）。

采用 pytest 原生写法的原因：负向用例不需要任何前置造数（不存在的ID直接写死即可），
fixture/YAML 驱动的收益为零，直接请求 + 断言最清晰。

用例之间零依赖：可单独运行、乱序运行，全部不需要前置造数。
"""
import time

import allure
import pytest
import requests

from common.auth import AUTH
from conf.operationConfig import OperationConfig

API_BASE = OperationConfig().get_section_for_data('api_envi', 'host')


def _auth_headers():
    return {'token': AUTH.token}


@allure.feature('单接口·负向')
class TestNegativeApi:

    @allure.story('商品详情·查询不存在的商品id')
    def test_product_detail_nonexistent_id(self):
        """实测契约：HTTP 200，error_code 4000，error '不存在该商品'，item 为空对象"""
        r = requests.post(f'{API_BASE}/coupApply/cms/productDetail',
                          json={'pro_id': '999999999999', 'page': 1, 'size': 20},
                          headers=_auth_headers(), verify=False, timeout=60)
        allure.attach(r.text, '商品详情负向响应', allure.attachment_type.TEXT)
        assert r.status_code == 200
        body = r.json()
        assert body['error_code'] == '4000'
        assert body['error'] == '不存在该商品'
        assert body['item'] == {}

    @allure.story('商品详情·商品id为空字符串')
    def test_product_detail_empty_id(self):
        """实测契约：空 id 与不存在的 id 同样返回 error_code 4000"""
        r = requests.post(f'{API_BASE}/coupApply/cms/productDetail',
                          json={'pro_id': '', 'page': 1, 'size': 20},
                          headers=_auth_headers(), verify=False, timeout=60)
        allure.attach(r.text, '商品详情负向响应', allure.attachment_type.TEXT)
        assert r.status_code == 200
        body = r.json()
        assert body['error_code'] == '4000'
        assert body['error'] == '不存在该商品'

    @allure.story('订单支付·支付不存在的订单号')
    def test_order_pay_nonexistent_order(self):
        """实测契约：HTTP 200，error_code 4000，error '订单编号或用户id不存在'"""
        r = requests.post(f'{API_BASE}/coupApply/cms/orderPay',
                          json={'orderNumber': '123456789012345678901',
                                'userId': '123456789012345678', 'timeStamp': int(time.time())},
                          headers=_auth_headers(), verify=False, timeout=60)
        allure.attach(r.text, '订单支付负向响应', allure.attachment_type.TEXT)
        assert r.status_code == 200
        body = r.json()
        assert body['error_code'] == '4000'
        assert body['error'] == '订单编号或用户id不存在'

    @allure.story('删除购物车·删除不存在的商品')
    def test_del_cart_nonexistent_product(self):
        """实测契约：HTTP 200，error_code 4000，error '购物车id不存在'
        （原孤儿 YAML 对此场景断言成功码 '0000'，负向断言方向写反了）"""
        r = requests.post(f'{API_BASE}/coupApply/cms/delCart',
                          data={'productId': '999999999999', 'timeStamp': int(time.time())},
                          headers=_auth_headers(), verify=False, timeout=60)
        allure.attach(r.text, '删除购物车负向响应', allure.attachment_type.TEXT)
        assert r.status_code == 200
        body = r.json()
        assert body['error_code'] == '4000'
        assert body['error'] == '购物车id不存在'
