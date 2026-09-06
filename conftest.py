# -*- coding: utf-8 -*-
import time

import pytest
import warnings

from pythonproject.base.removefile import remove_file
from pythonproject.common.dingRobot import send_dd_msg
from pythonproject.common.readyaml import ReadYamlData
from pythonproject.conf.setting import dd_msg

yfd = ReadYamlData()

import os
import pytest
from pythonproject.common.llm_analyzer import LLMAnalyzer

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