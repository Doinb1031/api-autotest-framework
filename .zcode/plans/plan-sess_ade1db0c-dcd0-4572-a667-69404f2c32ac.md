# 给造数 fixture 补 teardown 清理

## 改动（仅 `testcase/Single interface/test_dependent_api.py` 一个文件）

### 1. `cart_with_goods` 改为 yield 模式
- 造数后 `yield DOC_SAMPLE_GOODS_ID`，用例执行完自动进入 teardown
- teardown 调 delCart 清理，**幂等**：商品可能已被用例本身删掉（delCart 用例正是如此），返回 `0000`（成功）或 `4000`（不存在）都视为清理完成
- 清理失败不抛异常（不让 teardown 掩盖用例本身的结论），写入 Allure 附件留痕

### 2. `new_order` 补清理限制说明
- fixture docstring 明确写：接口文档不存在"取消/删除订单"API，订单无法清理，靠 mock 无状态兜底；指向真实服务时应改用取消订单接口或数据库清理任务

## 验证
- 单独跑 `test_dependent_api.py` 2 条通过（teardown 在用例成功与失败两种情况下都会执行，pytest 语义保证）
- 全套 1 次 37 条通过
- git commit 一次