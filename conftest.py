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