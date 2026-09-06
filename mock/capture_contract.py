# -*- coding: utf-8 -*-
"""对运行中的 exe mock 做全量契约探测，输出捕获文件供重写 mock 参考（临时脚本，不入库）。"""
import json
import time
import requests
import urllib3

urllib3.disable_warnings()
BASE = 'http://127.0.0.1:8787'
FORM = {'Content-Type': 'application/x-www-form-urlencoded;charset=UTF-8'}
JSONH = {'Content-Type': 'application/json;charset=UTF-8'}

out = []


def rec(name, r):
    body = r.text.strip()
    try:
        body = json.dumps(json.loads(body), ensure_ascii=False)
    except Exception:
        body = repr(body[:400])
    out.append(f'### {name}\nHTTP {r.status_code} {body}\n')
    print(name, r.status_code, body[:150])


# 1. 登录
r = requests.post(f'{BASE}/dar/user/login', data={'user_name': 'test01', 'passwd': 'admin123'}, headers=FORM, verify=False, timeout=10)
rec('登录成功(test01/admin123)', r)
token = r.json().get('token') or ''
H = {'token': token}

# 2. 登录边界
rec('登录-错密码', requests.post(f'{BASE}/dar/user/login', data={'user_name': 'test01', 'passwd': 'wrongpass123'}, headers=FORM, verify=False, timeout=10))
rec('登录-不存在用户', requests.post(f'{BASE}/dar/user/login', data={'user_name': 'nobody_user_2024', 'passwd': 'admin123'}, headers=FORM, verify=False, timeout=10))
rec('登录-缺密码', requests.post(f'{BASE}/dar/user/login', data={'user_name': 'test01'}, headers=FORM, verify=False, timeout=10))
rec('登录-全空', requests.post(f'{BASE}/dar/user/login', data={'user_name': '', 'passwd': ''}, headers=FORM, verify=False, timeout=10))

# 3. 用户管理（token 经历过失败登录，观察是否失效）
rec('addUser-新用户(失败登录后)', requests.post(f'{BASE}/dar/user/addUser', data={'username': f'probe_a_{int(time.time())}', 'password': 'tset6789890', 'role_id': '123456789', 'dates': '2023-12-31', 'phone': '13800000000', 'token': token}, headers=FORM, verify=False, timeout=10))
# 重新登录拿新 token
r = requests.post(f'{BASE}/dar/user/login', data={'user_name': 'test01', 'passwd': 'admin123'}, headers=FORM, verify=False, timeout=10)
token = r.json().get('token') or ''
H = {'token': token}
rec('重新登录后 addUser-新用户', requests.post(f'{BASE}/dar/user/addUser', data={'username': f'probe_b_{int(time.time())}', 'password': 'tset6789890', 'role_id': '123456789', 'dates': '2023-12-31', 'phone': '13800000000', 'token': token}, headers=FORM, verify=False, timeout=10))
rec('addUser-种子用户testadduser', requests.post(f'{BASE}/dar/user/addUser', data={'username': 'testadduser', 'password': 'tset6789890', 'role_id': '123456789', 'dates': '2023-12-31', 'phone': '13800000000', 'token': token}, headers=FORM, verify=False, timeout=10))
rec('addUser-缺token', requests.post(f'{BASE}/dar/user/addUser', data={'username': 'x', 'password': 'x', 'role_id': '1', 'dates': '2023-12-31', 'phone': '1', 'token': ''}, headers=FORM, verify=False, timeout=10))
rec('addUser-缺username', requests.post(f'{BASE}/dar/user/addUser', data={'password': 'x', 'role_id': '1', 'dates': '2023-12-31', 'phone': '1', 'token': token}, headers=FORM, verify=False, timeout=10))
rec('addUser-缺role_id', requests.post(f'{BASE}/dar/user/addUser', data={'username': 'x', 'password': 'x', 'dates': '2023-12-31', 'phone': '1', 'token': token}, headers=FORM, verify=False, timeout=10))
rec('updateUser-testadduser', requests.post(f'{BASE}/dar/user/updateUser', data={'username': 'testadduser', 'password': 'tset6789#$123', 'role_id': '89588181111112343', 'dates': '2023-12-31', 'phone': '13800000000', 'token': token}, headers=FORM, verify=False, timeout=10))
rec('updateUser-新用户名', requests.post(f'{BASE}/dar/user/updateUser', data={'username': 'probe_b_nonexist', 'password': 'x', 'role_id': '1', 'dates': '2023-12-31', 'phone': '1', 'token': token}, headers=FORM, verify=False, timeout=10))
rec('queryUser-种子id', requests.post(f'{BASE}/dar/user/queryUser', data={'user_id': '123839387391912', 'token': token}, headers=FORM, verify=False, timeout=10))
rec('queryUser-不存在id', requests.post(f'{BASE}/dar/user/queryUser', data={'user_id': '1238393873922', 'token': token}, headers=FORM, verify=False, timeout=10))
rec('deleteUser-种子id', requests.post(f'{BASE}/dar/user/deleteUser', data={'user_id': '123839387391912', 'token': token}, headers=FORM, verify=False, timeout=10))
rec('deleteUser-空id', requests.post(f'{BASE}/dar/user/deleteUser', data={'user_id': '', 'token': token}, headers=FORM, verify=False, timeout=10))
rec('deleteUser-缺参', requests.post(f'{BASE}/dar/user/deleteUser', data={'token': token}, headers=FORM, verify=False, timeout=10))

# 4. 商品域
rec('goodsList', requests.get(f'{BASE}/coupApply/cms/goodsList', params={'msgType': 'getHandsetListOfCust', 'page': 1, 'size': 20}, headers=H, verify=False, timeout=10))
r = requests.get(f'{BASE}/coupApply/cms/goodsList', params={'msgType': 'getHandsetListOfCust', 'page': 1, 'size': 20}, headers=H, verify=False, timeout=10)
goods = r.json()['goodsList'][0]
gid = goods['goodsId']
out.append(f'### goodsList[0] 完整结构\n{json.dumps(goods, ensure_ascii=False)}\n')
rec('productDetail-真实商品', requests.post(f'{BASE}/coupApply/cms/productDetail', json={'pro_id': gid, 'page': 1, 'size': 20}, headers=H, verify=False, timeout=10))
rec('productDetail-不存在', requests.post(f'{BASE}/coupApply/cms/productDetail', json={'pro_id': '999999999999', 'page': 1, 'size': 20}, headers=H, verify=False, timeout=10))
rec('productDetail-空id', requests.post(f'{BASE}/coupApply/cms/productDetail', json={'pro_id': '', 'page': 1, 'size': 20}, headers=H, verify=False, timeout=10))
rec('apiType', requests.post(f'{BASE}/coupApply/cms/apiType', data={}, headers=H, verify=False, timeout=10))

# 5. 购物车 + 订单链路
ts = int(time.time())
rec('shoppingJoinCart', requests.post(f'{BASE}/coupApply/cms/shoppingJoinCart', json={'goods_id': gid, 'count': 1, 'price': '1', 'timeStamp': ts}, headers=H, verify=False, timeout=10))
rec('delCart-存在的商品', requests.post(f'{BASE}/coupApply/cms/delCart', data={'productId': gid, 'timeStamp': int(time.time())}, headers=H, verify=False, timeout=10))
rec('delCart-不存在的商品', requests.post(f'{BASE}/coupApply/cms/delCart', data={'productId': '999999999999', 'timeStamp': int(time.time())}, headers=H, verify=False, timeout=10))
common = {'propertyChildIds': '2:9', 'inviter_id': '127839112', 'price': '1', 'freight_insurance': '0.00', 'discount_code': '002399', 'consignee_info': {'name': '张三', 'phone': '13800000000', 'address': '北京市海淀区'}}
rec('placeAnOrder-正常', requests.post(f'{BASE}/coupApply/cms/placeAnOrder', json={'goods_id': gid, 'number': 1, **common}, headers=H, verify=False, timeout=10))
r = requests.post(f'{BASE}/coupApply/cms/placeAnOrder', json={'goods_id': gid, 'number': 1, **common}, headers=H, verify=False, timeout=10)
order_no = r.json().get('orderNumber', '')
user_id = r.json().get('userId', '')
out.append(f'### placeAnOrder 完整结构\n{json.dumps(r.json(), ensure_ascii=False)}\n')
rec('placeAnOrder-缺number', requests.post(f'{BASE}/coupApply/cms/placeAnOrder', json={'goods_id': gid, **common}, headers=H, verify=False, timeout=10))
rec('placeAnOrder-number=0', requests.post(f'{BASE}/coupApply/cms/placeAnOrder', json={'goods_id': gid, 'number': 0, **common}, headers=H, verify=False, timeout=10))
rec('orderPay-正常', requests.post(f'{BASE}/coupApply/cms/orderPay', json={'orderNumber': order_no, 'userId': user_id, 'timeStamp': int(time.time())}, headers=H, verify=False, timeout=10))
rec('orderPay-不存在订单', requests.post(f'{BASE}/coupApply/cms/orderPay', json={'orderNumber': '123456789012345678901', 'userId': '123456789012345678', 'timeStamp': int(time.time())}, headers=H, verify=False, timeout=10))
rec('checkOrderStatus-新订单', requests.post(f'{BASE}/coupApply/cms/checkOrderStatus', json={'orderNumber': order_no, 'timeStamp': int(time.time())}, headers=H, verify=False, timeout=10))
rec('checkOrderStatus-不存在', requests.post(f'{BASE}/coupApply/cms/checkOrderStatus', json={'orderNumber': '999999999999', 'timeStamp': int(time.time())}, headers=H, verify=False, timeout=10))
rec('checkLogisticsStatus-不存在', requests.post(f'{BASE}/coupApply/cms/checkLogisticsStatus', json={'orderNumber': '999999999999', 'timeStamp': int(time.time())}, headers=H, verify=False, timeout=10))
rec('shoppingInventory-库存足(1件)', requests.post(f'{BASE}/coupApply/cms/shoppingInventory', json={'goodsId': '18382788819', 'count': '1', 'timeStamp': int(time.time())}, headers=H, verify=False, timeout=10))
rec('shoppingInventory-库存不足(6件)', requests.post(f'{BASE}/coupApply/cms/shoppingInventory', json={'goodsId': '18382788819', 'count': '6', 'timeStamp': int(time.time())}, headers=H, verify=False, timeout=10))
rec('shoppingInventory-空goodsId', requests.post(f'{BASE}/coupApply/cms/shoppingInventory', json={'goodsId': '', 'count': '1', 'timeStamp': int(time.time())}, headers=H, verify=False, timeout=10))

with open('mock/contract.md', 'w', encoding='utf-8') as f:
    f.write('\n'.join(out))
print('\nsaved to mock/contract.md, entries:', len(out))
