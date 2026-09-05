# ProductManager 套件：跨用例全局传参 → fixture 造数返回值

## 目标
单接口测试的"前置条件"改为 fixture 造数并返回值，用例之间零依赖；每个测试可单跑、可乱序、可并行。BusinessScenario.yml 链路（依赖是测试目标本身）保持不动。

## 改动清单

### 1. 新增 `testcase/ProductManager/conftest.py` — 造数 fixture
- `product_goods_id`（module 级）：跑 getProductList.yaml，返回一个可用商品ID
- `order_data(product_goods_id)`（module 级）：deepcopy commitOrder.yaml 的用例数据、注入商品ID、跑下单，返回 `{'orderNumber','userId'}`
- fixture 内部读上下文取提取值属于实现细节，**对测试暴露的是返回值**

### 2. 改造 `test_productList.py`
- `test_commit_order`：注入 `product_goods_id`（deepcopy 后改 testcase['json']['goods_id'] 再执行），不再依赖 getProductList 用例跑过
- `test_order_pay`：`order_pay_precondition` 换成 `order_data`，注入 orderNumber/userId
- **删除全部 `@pytest.mark.run(order=N)`**——造数自足后用例天然独立，不再需要顺序控制

### 3. YAML 调整
- `commitOrder.yaml`：`goods_id` 占位符改为空值 + 注释"运行时由 fixture 注入"
- `orderPay.yaml`：`orderNumber`/`userId` 占位符同样处理

### 4. 清理
- `testcase/conftest.py` 删除 `order_pay_precondition` 补数 fixture（存在理由消失）及因此不再使用的 import

## 验证标准
1. 全套 3 次运行通过（用例数不变，仍 21 条）
2. **单独运行 test_productList.py**（不跑其他套件）也通过——证明用例自足
3. 单独运行 test_order_pay 一条也通过（原来的痛点场景）
4. 磁盘无 extract.yaml，全程无变量缺失报错

## 提交
git commit 一次。