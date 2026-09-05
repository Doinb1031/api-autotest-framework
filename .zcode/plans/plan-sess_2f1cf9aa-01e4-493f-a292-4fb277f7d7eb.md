# 断言强化方案（可直接交给 AI 执行）

## 执行纪律（每个文件动手前必做）
用 curl/requests 先调一次目标接口，**确认真实响应字段**后再写断言——本方案的字段名已按此前实测结果给出，但执行时必须复核，禁止凭文档或想象写字段。

## 一、现状问题清单（按严重度）

| 类型 | 位置 | 问题 |
|---|---|---|
| D-框架缺陷 | assertions.py contains | jsonpath 在响应中找不到 key 时**静默通过**（resp_list 为空直接跳过），断言可能空转 |
| E-歪打正着 | ProductManager/productDetail.yaml | pro_id 实际发出的是逗号拼接的多 ID 垃圾串，断言 4000"碰巧"通过，用例语义与其名称不符 |
| A-缺协议层 | getProductList/commitOrder/queryUser/deleteUser | 无 status_code 断言 |
| B-弱关键词 | 全部 Single interface 用例、orderPay | contains 只查 msg 子串，应升级为 eq 精确相等 |
| C-内容层缺失 | goodsList 未验证非空 | goodsList 为空时 goodsId 提取空列表，后续用例静默劣化 |

## 二、框架层改造：`common/assertions.py`

新增 `exists` 断言类型（字段存在性），补上 contains 的静默通过告警：

```python
# assert_result() 的分发分支中新增：
elif key == 'exists':
    flag = self.exists_assert(value, response)

# 新增方法：
def exists_assert(self, value, response):
    """字段存在性断言。value 形如 {'$.goodsList[0]': True}：
    jsonpath 能取到值且与预期布尔一致则通过。"""
    flag = 0
    for expr, expected in value.items():
        found = jsonpath.jsonpath(response, expr)
        actual = bool(found)
        if actual != expected:
            flag += 1
            logs.error(f"存在性断言失败：{expr} 预期{'存在' if expected else '不存在'}，实际{'存在' if actual else '不存在'}")
            allure.attach(f"表达式：{expr}\n预期：{expected}\n实际：{actual}", '存在性断言结果：失败',
                          attachment_type=allure.attachment_type.TEXT)
        else:
            logs.info(f"存在性断言成功：{expr}")
    return flag

# contains_assert() 中 resp_list 为空处补告警（不改通过语义，避免破坏负向用例）：
if resp_list:
    ...
else:
    logs.warning(f"contains断言：响应中未找到字段【{assert_key}】，本断言未生效（空过）")
```

同时更新类头 docstring 的支持列表（加 exists）。YAML 中 exists 的位置跟随 contains（协议层/存在性在前，eq 在后）。

## 三、逐文件断言改法

### 1. `testcase/Business interface/BusinessScenario.yml`
- 步骤1 商品列表：在现有 contains status_code + eq error_code 之后**追加** `- exists: { '$.goodsList[0]': true }`（保证列表非空，goodsIds 提取才有意义）
- 步骤2 商品详情：**保持现状**，在 validation 上方加注释：`# mock 详情接口返回随机商品ID，无法做内容一致性断言，此为被测服务能力上限`
- 步骤3~7：已是三层断言，**不动**

### 2. `testcase/ProductManager/`
- `getProductList.yaml`：追加 `- contains: { 'status_code': 200 }` 和 `- exists: { '$.goodsList[0]': true }`
- `productDetail.yaml`：`pro_id` 改为 `${get_extract_data(goodsId,0)}`（取第一个真实商品）；validation 改为 `- contains: { 'status_code': 200 }` + `- eq: { 'error_code': '0000' }` + `- exists: { '$.item': true }`；case_name 改为"获取商品详情"（现名与行为不符的问题随 4000 断言一并消除）。注：依赖 ProductManager fixture 改造落地后此用例可单跑；fixture 未落地前仍靠执行顺序保证
- `commitOrder.yaml`：validation 最前面加 `- contains: { 'status_code': 200 }`（现有两个 eq 保留）
- `orderPay.yaml`：`- contains: { 'message': '订单支付成功' }` → `- eq: { 'error_code': '0000', 'message': '订单支付成功' }`，最前加 `- contains: { 'status_code': 200 }`

### 3. `testcase/Single interface/`
- `addUser.yaml`：正向用例 `- contains: { 'msg': '新增成功' }` → `- eq: { 'msg': '新增成功' }`；3 条负向用例的 `新增失败` 同样升为 eq；执行前先实测响应确认是否还有可断言字段（如 msg_code）
- `updateUser.yaml`：`contains msg 更新成功` → `eq { 'msg': '更新成功' }`（status_code contains 保留）
- `deleteUser.yaml`：4 条 contains msg 全部升 eq + 每条最前加 `- contains: { 'status_code': 200 }`；**修正第 3 条用例**："userid为空"实际传的是 `user_id: 1238393873922`，改为删除 `user_id` 字段（真·缺参），case_name 与行为对齐
- `queryUser.yaml`：追加 `- contains: { 'status_code': 200 }`；`contains msg 查询成功` → `eq { 'msg': '查询成功' }`（现有 eq msg_code 200 保留）

## 四、验证标准
1. 全套 pytest 3 次运行全部通过（21 条，用例数不变）
2. Allure 报告中抽查：每个正向用例至少含"协议层 + 业务码层"附件，链路与加购含内容层附件
3. exists 断言真实生效：临时把某处 goodsList 表达式改错应红，改回后绿（做一次人工验证即可）
4. grep 日志确认 contains 的空过告警只在预期场景出现
5. git commit 一次（信息中列出每文件断言层数变化）

## 五、明确不做的边界（写进用例注释）
- mock 不返回金额字段 → 价格勾稽断言不可行（commitOrder/orderPay）
- 详情接口返回随机商品 ID → 不做商品一致性断言
- config.ini 数据库为占位配置 → 不启用 db 断言