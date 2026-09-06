"""
测试执行入口。

CI 友好性约定：
- pytest.main 的返回值就是本进程的退出码：0=全部通过，1=有用例失败，其他=收集/内部错误。
  流水线平台（GitHub Actions / Jenkins 等）靠退出码判断这次运行是绿是红，绝不能吞掉。
- 报告生成不阻塞：allure 只落原始数据 + 本地尝试生成 HTML 并打开；
  allure CLI 未安装时（典型 CI 环境）静默跳过，CI 直接消费 junitxml / allure 原始数据。
"""
import os
import shutil
import subprocess
import sys
import webbrowser

import pytest
from conf.operationConfig import OperationConfig


def _report_type():
    """
    报告类型单一真相源：config.ini [REPORT_TYPE] type，环境变量 REPORT_TYPE 可覆盖。

    （原先 setting.py 与 config.ini 各存一份且互不同步，现统一为 config.ini 单一来源。）
    """
    return os.environ.get('REPORT_TYPE') or OperationConfig().get_report_type('type') or 'allure'


def run_with_allure():
    """执行全量用例并产出 allure 数据；返回 pytest 退出码。"""
    code = pytest.main(['-v', '--alluredir=./report/temp', './testcase', '--clean-alluredir',
                        '--junitxml=./report/results.xml'])
    try:
        shutil.copy('./environment.xml', './report/temp')
    except OSError as e:
        print(f'environment.xml 拷贝失败（不影响测试结果）: {e}')
    # allure CLI 只在本地存在时才生成 HTML 报告并打开；CI 环境跳过。
    # 报告生成属于锦上添花，任何失败都不能影响测试本身的退出码。
    allure_bin = shutil.which('allure')
    if allure_bin:
        try:
            subprocess.run([allure_bin, 'generate', './report/temp',
                            '-o', './report/allureReport', '--clean'], check=False)
            report_index = os.path.join(os.getcwd(), 'report', 'allureReport', 'index.html')
            if os.path.exists(report_index):
                webbrowser.open_new_tab(report_index)
        except OSError as e:
            print(f'allure 报告生成失败（不影响测试结果）: {e}')
    else:
        print('未检测到 allure CLI，跳过 HTML 报告生成（allure 原始数据与 junitxml 已生成）')
    return code


def run_with_tmreport():
    """执行全量用例并产出 tmreport HTML 报告；返回 pytest 退出码。"""
    code = pytest.main(['-v', '--pytest-tmreport-name=testReport.html',
                        '--pytest-tmreport-path=./report/tmreport'])
    webbrowser.open_new_tab(os.getcwd() + '/report/tmreport/testReport.html')
    return code


if __name__ == '__main__':
    report_type = _report_type()
    if report_type == 'allure':
        exit_code = run_with_allure()
    elif report_type == 'tm':
        exit_code = run_with_tmreport()
    else:
        print(f'未知的报告类型 [{report_type}]，按普通 pytest 执行')
        exit_code = pytest.main(['-v', './testcase'])
    # 透传退出码给操作系统：CI 平台据此判断本次运行成败
    sys.exit(exit_code)
