# -*- coding: utf-8 -*-
"""
电商物流 mock 服务（原 exe mock 的 Python 重实现）。

为什么重写：原 mock 是一个带 GUI 的 exe，只能在本地人工点击启动，无法进入 CI。
本服务按对 exe 的全量实测契约（_mock_contract.md 探测脚本输出）用 Flask 重实现，
使测试环境随仓库分发——pip install 后两条命令即可拉起完整测试环境。

与 exe 行为对齐的关键语义（均为实测确认，不是文档描述）：
1. 任何一次 /dar/user/login 调用（无论成败）都会使之前签发的 token 失效；
2. addUser 需要 有效token + username + role_id，但种子用户 testadduser 无条件放行；
   新增的用户不会进入"用户库"（对新增用户做 query/update 均失败）；
3. updateUser 只认种子用户 testadduser；
4. queryUser/deleteUser 只认种子用户ID 123839387391912，且可重复执行（无状态）；
5. checkOrderStatus 成功响应的 error_code 是空字符串（与其他接口的 '0000' 不同）；
6. shoppingInventory 库存阈值 6：count<6 状态 '0'，>=6 状态 '1' + '商品库存不足'；
7. checkLogisticsStatus 对存在的订单返回 status '1'（与文档 0=待发货 语义不符，
   沿用 exe 实测行为，差异已记录在 FulfillmentScenario.yml 注释中）。

启动：python mock/server.py（默认 127.0.0.1:8787，可用 MOCK_HOST/MOCK_PORT 环境变量覆盖）
"""
import os
import random
import sqlite3
import string
import threading
import time
from datetime import datetime

from flask import Flask, jsonify, request

app = Flask(__name__)
# 中文直接输出（与 exe 响应一致），避免报告中出现 \uXXXX 转义
app.json.ensure_ascii = False

# ---------- SQLite 持久化 ----------
# 业务数据（订单/用户/购物车）落一个 SQLite 文件，供测试的 db 断言查库验证——
# 让"三层断言"的数据库层有真实的数据可查。文件默认在 mock/ 目录（随仓库分发，
# 不入 git），可用环境变量 MOCK_DB 覆盖。
DB_PATH = os.environ.get('MOCK_DB', os.path.join(os.path.dirname(os.path.abspath(__file__)), 'mock.db'))


def init_db():
    """建库建表（幂等），进程启动时调用一次。"""
    with sqlite3.connect(DB_PATH) as conn:
        conn.executescript('''
            CREATE TABLE IF NOT EXISTS orders (
                order_number TEXT PRIMARY KEY,
                user_id      TEXT,
                status       TEXT,
                goods_id     TEXT,
                number       INTEGER,
                created_at   TEXT
            );
            CREATE TABLE IF NOT EXISTS users (
                username   TEXT PRIMARY KEY,
                created_at TEXT
            );
            CREATE TABLE IF NOT EXISTS cart_items (
                cid         INTEGER PRIMARY KEY,
                product_id  TEXT,
                product_name TEXT,
                price       TEXT,
                created_at  TEXT
            );
        ''')


def db_execute(sql, params=()):
    """执行一条写语句（INSERT/UPDATE/DELETE），自动提交。失败仅记录不中断请求。"""
    try:
        with sqlite3.connect(DB_PATH) as conn:
            conn.execute(sql, params)
            conn.commit()
    except sqlite3.Error as e:
        app.logger.error('SQLite 写入失败: %s, sql=%s', e, sql)


init_db()


# ---------- 全局状态（内存态，进程重启即重置） ----------

_LOCK = threading.Lock()

# 登录态：exe 的语义是"同一时刻只有一个有效 token"，任何 login 调用都会使其失效
_state = {'token': None}

# 种子数据：与 exe 一致的预置用户与商品
SEED_USER_ID = '123839387391912'
SEED_USERNAME = 'testadduser'
GOODS_LIST = [
    {"goodsId": "18382788819", "goods_count": "233",
     "goods_image": "https://omsproductionimg.yangkeduo.com/images/2017-12-12/bcf848aa71c6389607ae7a84b70f1543.jpeg",
     "goods_name": "【2件套】套装秋冬新款仿獭兔毛钉珠皮草毛毛短外套加厚大衣女装",
     "original_price": "", "unit_price": "￥99.00"},
    {"goodsId": "33809635011", "goods_count": "521",
     "goods_image": "https://omsproductionimg.yangkeduo.com/images/2017-12-12/176019babfdecffa1d9f98f40b7e99b4.jpeg",
     "goods_name": "好奇小森林心钻装纸尿裤M22拉拉裤L18/XL14超薄透气裤型尿不湿 1件装",
     "original_price": "", "unit_price": "￥108.00"},
    {"goodsId": "56996760797", "goods_count": "1181",
     "goods_image": "https://omsproductionimg.yangkeduo.com/images/2017-12-12/efb5db42397550bffd3211ca6f197498.jpeg",
     "goods_name": "冻干鸡小胸整块增肥营养发腮狗狗零食新手养猫零食幼猫零食100g",
     "original_price": "", "unit_price": "￥17.80"},
    {"goodsId": "82193785267", "goods_count": "3000+",
     "goods_image": "https://omsproductionimg.yangkeduo.com/images/2017-12-12/efb5db42397550bffd3211ca6f197498.jpeg",
     "goods_name": "【自营】ISB伊珊娜意大利水果系列宠物犬猫沐浴露除臭香波护毛素",
     "original_price": "", "unit_price": "￥650.00"},
    {"goodsId": "74190550836", "goods_count": "1000+",
     "goods_image": "https://omsproductionimg.yangkeduo.com/images/2017-12-12/efb5db42397550bffd3211ca6f197498.jpeg",
     "goods_name": "【新品零0CM嵌入式】海尔电冰箱410L家用法式四门多门官方正品",
     "original_price": "", "unit_price": "￥5746.00"},
]
# 购物车预置 3 件商品（与 exe 实测响应一致）
_cart = [
    {"cid": 26, "price": "108.00", "productId": "33809635011",
     "productImage": "https://omsproductionimg.yangkeduo.com/images/2017-12-12/bcf848aa71c6389607ae7a84b70f1543.jpeg",
     "productName": "好奇小森林心钻装纸尿裤M22拉拉裤L18/XL14超薄透气裤型尿不湿 1件装",
     "totalPrice": "347.00"},
    {"cid": 373, "price": "99.00", "productId": "18382788819",
     "productImage": "https://omsproductionimg.yangkeduo.com/images/2017-12-12/bcf848aa71c6389607ae7a84b70f1543.jpeg",
     "productName": "【2件套】套装秋冬新款仿獭兔毛钉珠皮草毛毛短外套加厚大衣女装",
     "totalPrice": "239.00"},
    {"cid": 497, "price": "17.80", "productId": "56996760797",
     "productImage": "https://omsproductionimg.yangkeduo.com/images/2017-12-12/efb5db42397550bffd3211ca6f197498.jpeg",
     "productName": "冻干鸡小胸整块增肥营养发腮狗狗零食新手养猫零食幼猫零食100g",
     "totalPrice": "364.80"},
]
_cid_seq = [600]
# 订单表：orderNumber -> {'userId': str, 'status': '0'已支付/'1'待支付}
_orders = {}


def _now():
    return datetime.now().strftime('%Y-%m-%d %H:%M:%S')


def _new_token():
    """生成 30 位混合大小写 token（与 exe 格式一致的随机串）。"""
    alphabet = string.ascii_letters + string.digits
    return ''.join(random.choices(alphabet, k=30))


def _request_token():
    """从请求中取 token：请求头或表单/JSON 参数体（与框架的注入方式对齐）。"""
    token = request.headers.get('token')
    if token:
        return token
    body = request.form.to_dict() or (request.get_json(silent=True) or {})
    return body.get('token') or ''


def _token_valid():
    """校验请求携带的 token 是否为当前有效 token。"""
    token = _request_token()
    with _LOCK:
        return bool(token) and token == _state['token']


# ---------- 用户模块 /dar/user ----------


@app.post('/dar/user/login')
def user_login():
    data = request.form.to_dict()
    user_name = data.get('user_name')
    passwd = data.get('passwd')
    # exe 语义：任何 login 调用（包括参数错误/登录失败）都会使旧 token 失效
    with _LOCK:
        _state['token'] = None
    if not user_name or not passwd:
        return jsonify({'msg': '参数错误', 'msg_code': -1})
    if user_name == 'test01' and passwd == 'admin123':
        token = _new_token()
        with _LOCK:
            _state['token'] = token
        return jsonify({'error_code': None, 'msg': '登录成功', 'msg_code': 200,
                        'orgId': '4140913758110176843', 'token': token,
                        'userId': '1097284939135638151'})
    return jsonify({'msg': '登录失败,用户名或密码错误', 'msg_code': 9001, 'token': None, 'userId': None})


@app.post('/dar/user/addUser')
def user_add():
    data = request.form.to_dict()
    # 实测语义：token 为空一律失败（即使种子用户）；种子用户带过期 token 反而放行
    if not data.get('token'):
        return jsonify({'msg': '新增失败，参数缺失或token失效', 'msg_code': 9001})
    if data.get('username') == SEED_USERNAME:
        db_execute('INSERT OR REPLACE INTO users (username, created_at) VALUES (?, ?)',
                   (SEED_USERNAME, _now()))
        return jsonify({'error_code': None, 'msg': '新增成功', 'msg_code': 200})
    if not _token_valid():
        return jsonify({'msg': '新增失败，参数缺失或token失效', 'msg_code': 9001})
    if not data.get('username') or not data.get('role_id'):
        return jsonify({'msg': '新增失败，参数缺失或token失效', 'msg_code': 9001})
    # 与 exe 一致：新增的用户不进入"用户库"（后续 query/update 均不可见），
    # 但落库留痕，供测试的 db 断言验证"新增动作确实发生"
    db_execute('INSERT OR REPLACE INTO users (username, created_at) VALUES (?, ?)',
               (data['username'], _now()))
    return jsonify({'error_code': None, 'msg': '新增成功', 'msg_code': 200})


@app.post('/dar/user/updateUser')
def user_update():
    data = request.form.to_dict()
    if data.get('username') == SEED_USERNAME:
        return jsonify({'error_code': None, 'msg': '更新成功', 'msg_code': 200})
    return jsonify({'msg': '更新失败', 'msg_code': 9001})


@app.post('/dar/user/queryUser')
def user_query():
    data = request.form.to_dict()
    if data.get('user_id') == SEED_USER_ID:
        return jsonify({'error_code': None, 'msg': '查询成功!', 'msg_code': 200})
    return jsonify({'msg': '查询失败，用户id不存在!', 'msg_code': 9001})


@app.post('/dar/user/deleteUser')
def user_delete():
    data = request.form.to_dict()
    if data.get('user_id') == SEED_USER_ID:
        return jsonify({'error_code': None, 'msg': '删除成功!', 'msg_code': 200})
    return jsonify({'msg': '删除失败，用户id不存在!', 'msg_code': 9001})


# ---------- 电商模块 /coupApply/cms ----------


@app.get('/coupApply/cms/goodsList')
def goods_list():
    return jsonify({'api_info': 'today:21 max:10000 all[90=21+33+36];expires:2030-12-31',
                    'cache': 0, 'error_code': '0000', 'goodsList': GOODS_LIST,
                    'reason': '', 'request_id': 'request_id',
                    'secache': 'c98b29872e8a4b28859db207944ba817',
                    'secache_date': _now(),
                    'secache_time': int(time.time() * 1000),
                    'translate_language': 'zh-CN'})


@app.post('/coupApply/cms/productDetail')
def product_detail():
    data = request.get_json(silent=True) or {}
    pro_id = str(data.get('pro_id') or '')
    goods = next((g for g in GOODS_LIST if g['goodsId'] == pro_id), None)
    if goods is None:
        return jsonify({'error': '不存在该商品', 'error_code': '4000', 'goodsId': '',
                        'item': {}, 'secache_date': _now(), 'translate_language': 'zh-CN'})
    price = float(goods['unit_price'].replace('￥', ''))
    item = {'AmountOnSale': 3188, 'CategoryId': 8484,
            'Delivery': {'Postage': '快递 免运费'},
            'ImageUrls': [goods['goods_image']], 'PriceRangeInfos': [{'Price': price}],
            'ProductFeatures': {'面料材质': '仿皮草', '版型': '修身'},
            'SellCount': '已拼4.2万件', 'ShopId': '461742',
            'ShopName': '果果家气质女装', 'Subject': goods['goods_name'],
            'Unit': None, 'format_check': 'ok'}
    return jsonify({'api_type': 'pinduoduo', 'cache': 0,
                    'call_args': {'num_iid': '1620002566'}, 'error': '',
                    'error_code': '0000', 'goodsId': goods['goodsId'], 'item': item,
                    'reason': '', 'request_id': 'gw-4.63510267214bd',
                    'secache_date': _now(), 'translate_language': 'zh-CN'})


@app.post('/coupApply/cms/apiType')
def api_type():
    return jsonify({'error_code': '0000', 'status': ['all', 'pinduoduo']})


@app.post('/coupApply/cms/shoppingJoinCart')
def shopping_join_cart():
    data = request.get_json(silent=True) or {}
    goods_id = str(data.get('goods_id') or '')
    goods = next((g for g in GOODS_LIST if g['goodsId'] == goods_id), None)
    if goods is None:
        return jsonify({'error': '商品不存在', 'error_code': '4000', 'message': '',
                        'translate_language': 'zh-CN'})
    with _LOCK:
        _cid_seq[0] += 1
        cid = _cid_seq[0]
        cart_item = {'cid': cid,
                     'price': goods['unit_price'].replace('￥', ''),
                     'productId': goods['goodsId'],
                     'productImage': goods['goods_image'],
                     'productName': goods['goods_name'],
                     'totalPrice': goods['unit_price'].replace('￥', '')}
        _cart.append(cart_item)
        cart_snapshot = [dict(i) for i in _cart]
    db_execute('INSERT OR REPLACE INTO cart_items (cid, product_id, product_name, price, created_at) VALUES (?, ?, ?, ?, ?)',
               (cid, goods['goodsId'], goods['goods_name'], cart_item['price'], _now()))
    return jsonify({'cartList': cart_snapshot, 'createTime': _now(), 'error': '',
                    'error_code': '0000', 'message': 'success',
                    'translate_language': 'zh-CN', 'userId': '1097284939135638151'})


@app.post('/coupApply/cms/delCart')
def del_cart():
    data = request.form.to_dict()
    product_id = str(data.get('productId') or '')
    with _LOCK:
        found = next((i for i in _cart if i['productId'] == product_id), None)
        if found is None:
            return jsonify({'createTime': _now(), 'error': '购物车id不存在',
                            'error_code': '4000', 'message': '',
                            'translate_language': 'zh-CN'})
        _cart.remove(found)
    db_execute('DELETE FROM cart_items WHERE product_id = ?', (product_id,))
    return jsonify({'createTime': _now(), 'error': '', 'error_code': '0000',
                    'message': 'success', 'translate_language': 'zh-CN'})


@app.post('/coupApply/cms/placeAnOrder')
def place_an_order():
    data = request.get_json(silent=True) or {}
    goods_id = str(data.get('goods_id') or '')
    number = data.get('number')
    if not goods_id or not isinstance(number, (int, float)) or number <= 0:
        return jsonify({'error': '参数错误或必填参数为空', 'error_code': '9001'})
    order_number = ''.join(random.choices(string.digits, k=21))
    user_id = '1097284939135638151'
    with _LOCK:
        # exe 实测：无论是否支付，订单状态查询固定返回 '0'
        _orders[order_number] = {'userId': user_id, 'status': '0'}
    db_execute('INSERT OR REPLACE INTO orders (order_number, user_id, status, goods_id, number, created_at) VALUES (?, ?, ?, ?, ?, ?)',
               (order_number, user_id, '0', str(data.get('goods_id') or ''), number, _now()))
    # 注意 "crateTime" 拼写是 exe 的原样行为，用例契约依赖此结构
    return jsonify({'crateTime': _now(), 'error': '', 'error_code': '0000',
                    'message': '提交订单成功', 'orderNumber': order_number,
                    'translate_language': 'zh-CN', 'userId': user_id})


@app.post('/coupApply/cms/orderPay')
def order_pay():
    data = request.get_json(silent=True) or {}
    order_number = str(data.get('orderNumber') or '')
    with _LOCK:
        order = _orders.get(order_number)
        if order is None:
            return jsonify({'error': '订单编号或用户id不存在', 'error_code': '4000'})
    return jsonify({'createTime': _now(), 'error': '', 'error_code': '0000',
                    'message': '订单支付成功', 'translate_language': 'zh-CN'})


@app.post('/coupApply/cms/checkOrderStatus')
def check_order_status():
    data = request.get_json(silent=True) or {}
    order_number = str(data.get('orderNumber') or '')
    with _LOCK:
        order = _orders.get(order_number)
        if order is None:
            return jsonify({'error': '订单编号不存在', 'error_code': '4000'})
        status = order['status']
    # 成功响应的 error_code 为空字符串，是 exe 的实测契约（与 '0000' 不同）
    return jsonify({'error': '', 'error_code': '', 'queryTime': _now(),
                    'status': status, 'translate_language': 'zh-CN'})


@app.post('/coupApply/cms/checkLogisticsStatus')
def check_logistics_status():
    data = request.get_json(silent=True) or {}
    order_number = str(data.get('orderNumber') or '')
    with _LOCK:
        exists = order_number in _orders
    if not exists:
        return jsonify({'error': '订单编号不存在', 'error_code': '4000'})
    # exe 对存在的订单固定返回 status '1'（与文档 0=待发货 不符，按实测契约实现）
    return jsonify({'error': '', 'error_code': '0000', 'queryTime': _now(),
                    'status': '1',
                    'logisticsInfo': {'company': '测试快递', 'no': 'SF' + order_number[-10:]},
                    'translate_language': 'zh-CN'})


@app.post('/coupApply/cms/shoppingInventory')
def shopping_inventory():
    data = request.get_json(silent=True) or {}
    goods_id = str(data.get('goodsId') or '')
    if not goods_id:
        return jsonify({'error_code': '9001', 'msg': '参数错误'})
    count = data.get('count')
    try:
        count = int(count)
    except (TypeError, ValueError):
        return jsonify({'error_code': '9001', 'msg': '参数错误'})
    # 与 exe 一致：库存阈值 6，count>=6 报库存不足但 error_code 仍为 '0000'
    if count >= 6:
        return jsonify({'createTime': _now(), 'error': '商品库存不足',
                        'error_code': '0000', 'status': '1',
                        'translate_language': 'zh-CN'})
    return jsonify({'createTime': _now(), 'error': '', 'error_code': '0000',
                    'status': '0', 'translate_language': 'zh-CN'})


if __name__ == '__main__':
    host = os.environ.get('MOCK_HOST', '127.0.0.1')
    port = int(os.environ.get('MOCK_PORT', '8787'))
    app.run(host=host, port=port, threaded=True)
