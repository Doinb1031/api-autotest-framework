# -*- coding: utf-8 -*-
import os
import sys
import time

import pytest
import warnings

# 本项目所有模块使用 `from base/common/conf/...` 平铺导入，前提是仓库根目录在 sys.path 里。
# 本地跑 pytest 时该前提由多种隐式行为兜底，CI 容器（bare `pytest` 命令、checkout 目录名不同）
# 下不成立，这里显式插入仓库根目录，保证任意 cwd / pytest 版本 / CI 环境下导入路径一致。
# 注意：不要用本地目录名硬编码包路径（如 `from <本地文件夹名>.xxx import`）——
# GitHub checkout 目录名与本地不同，这类导入在 CI 上必然失败。
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from base.removefile import remove_file
from common.dingRobot import send_dd_msg
from common.readyaml import ReadYamlData
from conf.setting import dd_msg

yfd = ReadYamlData()

import os
import pytest
from common.llm_analyzer import LLMAnalyzer

# 从环境变量读取 API Key（建议设置环境变量 ALIYUN_API_KEY）
API_KEY = os.getenv("ALIYUN_API_KEY")
BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
MODEL = "deepseek-v3.2"  # 使用的模型名称

# 初始化 LLM 分析器
analyzer = LLMAnalyzer(api_key=API_KEY, model=MODEL, base_url=BASE_URL)


def pytest_addoption(parser):
    """
    注册命令行参数 --env，实现多环境切换：
        pytest --env=test          # 跑 test 环境
        pytest                     # 不传则读环境变量 TEST_ENV，再默认 local
    优先级：--env 命令行参数 > TEST_ENV 环境变量 > 默认 local。
    """
    parser.addoption('--env', default=None,
                     help='目标环境名，对应 config.ini 的 [api_envi:<env>] 段，默认 local')


def pytest_configure(config):
    """
    把 --env 参数桥接为环境变量 TEST_ENV。

    配置层（operationConfig.get_api_env）读取的是 TEST_ENV 环境变量——
    这是因为 OperationConfig 在模块导入阶段就会被实例化，拿不到 pytest 的
    config 对象；环境变量是 pytest 参数与配置层之间的标准桥接方式，
    同时也让不经过 pytest 的脚本（CI、造数脚本）能用 TEST_ENV 直接切环境。
    pytest_configure 在用例收集/导入之前执行，保证时序正确。
    """
    env = config.getoption('--env') or os.environ.get('TEST_ENV') or 'local'
    os.environ['TEST_ENV'] = env
    print(f'\n>>> 当前测试环境：{env}（config.ini 的 [api_envi:{env}] 段，未定义则回落 [api_envi]）')


def pytest_collection_modifyitems(items):
    """给所有用例自动打上 regression 标记：全量即回归，无需在每个文件手动标记。"""
    for item in items:
        item.add_marker(pytest.mark.regression)


@pytest.hookimpl(tryfirst=True, hookwrapper=True)
def pytest_runtest_makereport(item, call):
    outcome = yield
    report = outcome.get_result()

    if report.when == "call" and report.failed:
        # 获取 traceback
        longrepr = report.longrepr
        if hasattr(longrepr, "reprcrash"):
            traceback_text = str(longrepr.reprcrash)
        else:
            traceback_text = str(longrepr)

        suggestion = analyzer.analyze_error_sync(test_name=item.nodeid, traceback=traceback_text)
        if suggestion:
            print(f"\nAI 建议：\n{suggestion}\n")