"""
token 过期与自动刷新专项用例（原生 pytest）。

覆盖 common/auth.py + common/sendrequest.py 的 token 双层自愈：
- 请求前检查（refresh_if_needed）：token 逼近过期时，发请求前自动重建，一次成功；
- 请求后检查（is_invalid_response + refresh_and_retry_token）：服务端已判失效时，
  第一次请求失败后自动重建并重试一次成功；
- 回归守护：${get_auth_token()} 占位符始终解析到最新 token（刷新时机先于占位符替换）。

依赖 mock 的测试控制端点 POST /__mock/expires_in（mock/server.py，非 exe 契约，
仅测试用）：在不重启 mock 的前提下把 token 有效期调短，制造"服务端已过期、
客户端不知道"的场景。用例会改动 AUTH 全局登录态与 mock 有效期，teardown 统一恢复。

若改动 4（刷新提前到 replace_load 前）被回退，test_adduser_header_token_no_waste
会因"header 旧 token → 失效 → 重试二次登录"断言失败，起回归守护作用。
"""
import time

import pytest

from base.apiutil import RequestBase
from common.auth import AUTH, AuthState
from common.httpclient import SESSION, HTTP_TIMEOUT
from conf.operationConfig import OperationConfig

# 当前环境的接口 base url（多环境：pytest --env / TEST_ENV 决定读 config.ini 哪个段）
API_BASE = OperationConfig().get_api_env('host')
# mock 默认有效期（与 mock/server.py 的 MOCK_EXPIRES_IN 默认值一致）
_DEFAULT_EXPIRES_IN = 3600


@pytest.fixture(autouse=True)
def _restore_auth_state():
    """用例结束后恢复 mock 有效期与登录态，避免污染同进程后续用例（system_login 是 session 级，不会重跑）。"""
    yield
    _mock_set_expires_in(_DEFAULT_EXPIRES_IN)
    AUTH.login()


def _mock_set_expires_in(seconds):
    """调用 mock 测试控制端点调整 token 有效期（秒）。"""
    r = SESSION.post(f'{API_BASE}/__mock/expires_in', json={'expires_in': seconds},
                     timeout=HTTP_TIMEOUT)
    assert r.status_code == 200, f'控制端点设置有效期失败: {r.text}'
    body = r.json()
    assert body.get('ok') is True, f'控制端点返回异常: {body}'


def _install_login_spy(monkeypatch):
    """把 AUTH.login 包一层计数 spy，返回 (计数器列表, 原始方法引用)。"""
    calls = []
    original = AUTH.login

    def spy(*args, **kwargs):
        calls.append(1)
        return original(*args, **kwargs)

    monkeypatch.setattr(AUTH, 'login', spy)
    return calls, original


def test_pre_request_refresh(monkeypatch):
    """请求前检查：token 逼近过期时，发请求前自动重建，且一次成功（无失效重试）。"""
    AUTH.token_expire_time = int(time.time()) + 1  # 强制进入"临近过期"窗口（teardown 会重登复位）
    calls, _ = _install_login_spy(monkeypatch)

    base_info = {'api_name': '商品详情', 'url': '/coupApply/cms/productDetail', 'method': 'POST',
                 'header': {'Content-Type': 'application/json'}}
    test_case = {'case_name': '请求前自动刷新',
                 'json': {'pro_id': '0', 'page': 1, 'size': 20},
                 'validation': [{'contains': {'status_code': 200}}]}
    RequestBase().specification_yaml(base_info, test_case)

    assert len(calls) == 1, f'预期仅请求前 1 次登录刷新，实际 {len(calls)} 次'


def test_post_request_expiry_retry(monkeypatch):
    """请求后检查：服务端已过期而客户端不知情时，第一次失败→自动重建→重试成功。"""
    # 复位到"刚登录、客户端按服务器说的 3600 秒估算"的基线
    AUTH.login()
    old_token = AUTH.token
    # 登录之后再把服务器有效期收紧到 2 秒：已签发的 token 2 秒后过期，但客户端
    # token_expire_time 仍是登录时按 3600 算的，不知道服务器已经变卦
    _mock_set_expires_in(2)
    time.sleep(2.5)
    calls, _ = _install_login_spy(monkeypatch)
    assert int(time.time()) < AUTH.token_expire_time, '前置条件失败：客户端应仍认为 token 有效'

    base_info = {'api_name': '新增用户', 'url': '/dar/user/addUser', 'method': 'POST',
                 'header': {'Content-Type': 'application/x-www-form-urlencoded;charset=UTF-8'}}
    test_case = {'case_name': '服务端过期后自动重建重试',
                 'data': {'username': 'expiry_retry_user', 'password': 'x', 'role_id': '1',
                          'dates': '2026-09-08', 'phone': '13800000000',
                          'token': '${get_auth_token()}'},
                 'validation': [{'eq': {'msg': '新增成功', 'msg_code': 200}}]}
    RequestBase().specification_yaml(base_info, test_case)

    assert AUTH.token != old_token, 'token 应在失效重建后更换'
    assert len(calls) == 1, f'预期仅 1 次失效重建登录，实际 {len(calls)} 次'


def test_adduser_header_token_no_waste(monkeypatch):
    """回归守护：header 显式写 ${get_auth_token()} 时，刷新必须先于占位符替换。

    若刷新晚于替换，header 会带着旧 token 发出（先失败），重试逻辑补一次登录——
    spy 计数变 2，本用例失败。
    """
    AUTH.token_expire_time = int(time.time()) + 1  # 强制请求前刷新发生（teardown 会重登复位）
    calls, _ = _install_login_spy(monkeypatch)

    base_info = {'api_name': '新增用户(header携带token)',
                 'url': '/dar/user/addUser', 'method': 'POST',
                 'header': {'Content-Type': 'application/x-www-form-urlencoded;charset=UTF-8',
                            'token': '${get_auth_token()}'}}
    test_case = {'case_name': 'header token 不浪费请求',
                 'data': {'username': 'header_token_user', 'password': 'x', 'role_id': '1',
                          'dates': '2026-09-08', 'phone': '13800000000',
                          'token': '${get_auth_token()}'},
                 'validation': [{'eq': {'msg': '新增成功', 'msg_code': 200}}]}
    RequestBase().specification_yaml(base_info, test_case)

    assert len(calls) == 1, f'预期仅请求前 1 次刷新登录（无失效重试），实际 {len(calls)} 次'


def test_advance_clamp_guard(monkeypatch):
    """配置守护：refresh_advance_seconds >= expire_seconds 时钳制为 expire/3，防止"每请求先登录"。"""
    original = OperationConfig.get_section_for_data

    def fake_bad(self, section, option):
        values = {'expire_seconds': '100', 'refresh_advance_seconds': '300'}
        return values.get(option) if option in values else original(self, section, option)

    monkeypatch.setattr(OperationConfig, 'get_section_for_data', fake_bad)
    state = AuthState()
    assert state.token_expire_seconds == 100
    assert state.refresh_advance_seconds == max(100 // 3, 1) == 33

    def fake_ok(self, section, option):
        values = {'expire_seconds': '300', 'refresh_advance_seconds': '60'}
        return values.get(option) if option in values else original(self, section, option)

    monkeypatch.setattr(OperationConfig, 'get_section_for_data', fake_ok)
    state_ok = AuthState()
    assert state_ok.token_expire_seconds == 300
    assert state_ok.refresh_advance_seconds == 60