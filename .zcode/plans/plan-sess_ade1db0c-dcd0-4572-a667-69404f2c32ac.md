# 按接口文档补写三类用例（断言从实测出发）

## 设计原则
- 三类用例各归其位：不依赖=独立 yaml；依赖=fixture 造数返回值；流程=链路 yaml（context 传参）
- **所有断言值必须先实测**（这套 mock 有自己的怪脾气），实现第 0 步用 requests 把每个场景的真实响应探一遍，只把实测到的值写进断言
- 断言分层：status_code + 业务码 + message + 能做内容断言的做内容断言（数据回显/状态枚举值）
- 唯一化：造数用户名用 `${timestamp()}` 拼接，重跑不冲突（幂等）

## A. 单接口·不依赖（新增约 5 条）
新建 `testcase/Single interface/checkStatus.yaml` + 新 runner `test_check_api.py`：
1. checkOrderStatus：编造不存在的订单号 → 实测已确认 `error_code 4000 + error 订单编号不存在`，加 status_code
2. checkOrderStatus：orderNumber 为空 → 探测后按实测写
3. checkLogisticsStatus：不存在订单号 → 探测后按实测写
4. shoppingInventory：文档示例商品 18382788819 + count 边界（1/超大批量）→ 文档定义 status 0=正常/1=不足，探测确认 mock 阈值后写两条
5. `login.yaml` 追加：参数缺失（只传 user_name）→ 按实测 msg/msg_code 写

## B. 单接口·依赖（2 条，fixture 造数）
新建 `testcase/Single interface/test_dependent_api.py`（fixture 写在文件内）：
1. **delCart 正向**：fixture 调加购（文档示例商品ID）→ 测试删除该商品 → 0000 + message success
2. **checkOrderStatus 状态校验**：fixture 走下单（复用 ProductManager 的造数思路，含商品列表）→ 测试查新订单状态 → 断言 status 为文档定义的合法枚举值（实测定值）
- 探测 addUser 是否返回新用户 ID 及 queryUser 是否回显数据；若回显则追加第 3 条"新增→查询数据回显一致"，mock 无状态则不做（不强写假用例）

## C. 业务流程（1 条，6 步链路）
首选**用户全生命周期**（区别于已有购物链路，走文档第一节的 /dar/user/*）：
新增（唯一用户名，extract user_id）→ 查询 → 修改 → 再查询（验证修改生效的数据回显）→ 删除 → 再查询（确认已删）
- 写成 `testcase/Business interface/UserScenario.yml` + `test_user_scenario.py`（复用 apiutil_business 链路模式）
- **实现第 0 步探测时若 mock 对用户无状态**（查询/修改/删除不体现新建用户），则这条流程改用已验证有状态的电商履约流程：商品列表→加购→下单→支付→查订单状态(0)→查物流状态(0=待发货)→删购物车，决策依据写进最终说明

## 验证标准
1. 全套 3 次运行通过（新增约 8 条用例后总数约 29 条）
2. 新 runner 单独跑、单条依赖用例单独跑均通过
3. Allure 报告里每条新用例的断言附件可见（成功证据）
4. 磁盘无 extract.yaml，无变量缺失报错

## 提交
git commit 一次。