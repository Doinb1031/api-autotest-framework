# extract.yaml 落盘方案 → 内存业务上下文（真实工作模式）

## 背景与定性
"提取变量供后续接口引用"是行业标准机制（JMeter/Postman/httprunner/Karate 全都有），不合适的只是**落盘存储**。真实框架中同一次运行内的变量全部在内存上下文里传递，随运行销毁。占位符语法 `${get_extract_data(...)}` 保持不变，YAML 用例零改动。

## 改动清单

### 1. 新增 `common/context.py` — 内存业务上下文
- 模块级 dict + 线程锁，`set_vars`（后写覆盖先写）/ `get_var`（找不到记日志返回 None，语义与原文件方案一致）/ `clear` / `snapshot`（调试用）

### 2. 改造 `common/readyaml.py` — 读写后端换内存
- `write_yaml_data` → 调 `context.set_vars`（不再 append 到文件，重复 key 问题自然消失）
- `get_extract_yaml` → 调 `context.get_var`
- `clear_yaml_data` → 调 `context.clear`
- 删除文件 I/O 和 `FILE_PATH['EXTRACT']` 依赖
- 对外方法签名不变，apiutil/apiutil_business/debugtalk 的调用零改动

### 3. 清理残留
- `conf/setting.py` 的 `FILE_PATH['EXTRACT']` 条目删除（grep 确认无其他引用后）
- 磁盘上的 extract.yaml 遗留文件删除
- conftest 里 clear 的注释措辞更新
- `.gitignore` 里 extract.yaml 条目保留（防将来误生成）

## 验证标准
1. 全套 3 次运行 21 条全部通过（goodsIds 索引取值、orderNumber 链路传参、order_pay_precondition 均依赖此机制，绿即证明语义等价）
2. 运行全程磁盘上不再生成 extract.yaml
3. `${get_auth_token()}`（token 内存方案）与业务变量（内存上下文）两条内存链路互不干扰

## 提交
git commit 一次。