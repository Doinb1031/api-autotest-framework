# Token 管理全面重构：从 extract.yaml 落盘改为内存注入

## 目标
对齐真实工作主流做法：token 登录后保存在内存（session 级），由请求层统一注入；extract.yaml 降级为只存业务数据（orderNumber、goodsIds 等）；日志/Allure 报告中的敏感值掩码。

## 改动清单

### 1. 新增 `common/auth.py` — 内存认证状态中心
- `AuthState`：模块级保存 `token`、`token_expire_time`、`cookies`（JWT access_token_cookie），带线程锁
- `login()`：复用 `data/loginName.yaml` 的账号数据和 `conf/config.ini` 的 host，调登录接口，成功后写入 AuthState（不再写 extract.yaml）
- `refresh_if_needed()`：把现在 `sendrequest.ensure_token_valid` 的"提前刷新"逻辑迁来，基于内存过期时间判断
- `is_invalid_response()`：把 `_is_token_invalid` 的判定逻辑（401/403 状态码、失效错误码、关键词）迁来
- 复用现有 `[TOKEN]` 配置段（config.ini），配置读取方式不变

### 2. 改造 `common/sendrequest.py` — 请求层统一注入
- `run_main` 发请求前：从 AuthState 取 token 自动注入请求头（登录请求本身除外，保留 `_refreshing` 防递归标志）
- `ensure_token_valid` / `login_and_refresh_token`：改为调用 AuthState，token/过期时间/Cookie 全部只写内存；删除写 extract.yaml 的代码
- Cookie 跟随 AuthState 注入（替代现在从 extract.yaml 读 Cookie 的路径）
- **敏感值掩码**：新增 `mask_sensitive()`，对所有 `logs.info` 的请求头/Cookie/响应和 `allure.attach` 的附件先掩码（token、access_token_cookie 显示为前 4 位 + ****）

### 3. 改造 `testcase/conftest.py`
- `system_login` fixture：改为调 `auth.login()`（不再把 loginName.yaml 当用例跑），断言登录成功；保留每次运行前清空 extract.yaml 的逻辑（业务数据卫生）
- orderPay 前置补数据的 fixture 不动（业务数据仍走 extract.yaml）

### 4. 清理所有 YAML 的 token 痕迹
- 删除所有 baseInfo header 里的 `token: ${get_extract_data(token)}` 行（涉及 Single interface、Business interface 链路 + test_07~12、ProductManager 各 yaml）
- `data/loginName.yaml` 删除 `extract: token: $.token`（token 不再落盘）
- **业务数据提取全部保留**（goodsIds、orderNumber、userId 等，extract.yaml 机制不变）
- 注意：ProductManager 的 `login_dw.yaml` 是另一个登录入口，实现时单独检查其数据流

### 5. 不动的部分
- `debugtalk.get_extract_data` 机制原样保留（业务数据仍需它）
- `apiutil.py` / `apiutil_business.py` 的 replace_load 与断言流程不动
- 现有 27→21 条用例的业务断言不动

## 验证标准
1. 全套 pytest 3 次运行全部通过（当前基线 21 passed）
2. 运行后 extract.yaml 中不再出现 `token` / `token_expire_time` / `Cookie` 键，只有业务数据
3. 日志文件和 Allure 报告中 token 显示为掩码（如 `F5C0****`），grep 不到完整 token
4. token 过期刷新路径仍可用（AuthState 内存过期时间驱动，机制保留）

## 提交
完成后 git commit 一次（仓库已初始化，可回滚）。