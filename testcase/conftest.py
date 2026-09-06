import pytest
import allure
from common.readyaml import ReadYamlData
from common.auth import AUTH
from common.recordlog import logs
from common.connection import ConnectSQLite

# mock 落库的 SQLite 表结构（与 mock/server.py 的 init_db 保持一致）；
# 会话开始时幂等建表 + 清空，保证 db 断言不受历史残留影响、可重复执行
MOCK_DB_SCRIPT = '''
CREATE TABLE IF NOT EXISTS orders (
    order_number TEXT PRIMARY KEY, user_id TEXT, status TEXT,
    goods_id TEXT, number INTEGER, created_at TEXT
);
CREATE TABLE IF NOT EXISTS users (
    username TEXT PRIMARY KEY, created_at TEXT
);
CREATE TABLE IF NOT EXISTS cart_items (
    cid INTEGER PRIMARY KEY, product_id TEXT, product_name TEXT,
    price TEXT, created_at TEXT
);
DELETE FROM orders;
DELETE FROM users;
DELETE FROM cart_items;
'''

"""
-function：每一个函数或方法都会调用
-class：每一个类调用一次，一个类中可以有多个方法
-module：每一个.py文件调用一次，该文件内又有多个function和class
-session：是多个文件调用一次，可以跨.py文件调用，每个.py文件就是module,整个会话只会运行一次
- autouse：默认为false，不会自动执行，需要手动调用，为true可以自动执行，不需要调用
- yield：前置、后置
"""

yfd = ReadYamlData()


@pytest.fixture(autouse=True)
def start_test_and_end():
    logs.info('-------------接口测试开始--------------')
    yield
    logs.info('-------------接口测试结束--------------')


@pytest.fixture(scope='session', autouse=True)
@allure.story("登录")
def system_login():
    # 清空内存业务上下文，避免上次运行的业务数据残留影响本次测试
    # 登录态（token/Cookie）由 auth 模块保存在内存，不落盘
    yfd.clear_yaml_data()
    try:
        body = AUTH.login()
        assert body.get('msg') == '登录成功', '登录接口返回异常：%s' % body
    except Exception as e:
        logs.error(f'登录接口出现异常，导致后续接口无法继续运行，请检查程序！，{e}')
        pytest.fail('登录失败，后续接口无法执行：%s' % e)


@pytest.fixture(scope='session', autouse=True)
def datadb_init():
    """
    数据库前置：会话开始时对 mock 落库的 SQLite 做幂等建表 + 清空。

    - 保证 db 断言（三层断言的数据库层）从干净状态开始，可重复执行；
    - 表结构与 mock/server.py 的 init_db 一致，mock 未启动时测试也能正常建表
      （但 db 断言会因查不到数据而失败——这是正确行为：数据没写进来就该失败）。
    """
    conn = ConnectSQLite()
    conn.execute_script(MOCK_DB_SCRIPT)
    logs.info('mock 落库已就绪（建表 + 清理完成）')
    yield
    allure.attach('mock 落库测试数据已在会话开始时清空', 'fixture', allure.attachment_type.TEXT)
