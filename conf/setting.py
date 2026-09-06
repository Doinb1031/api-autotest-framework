import logging
import os
import sys

DIR_BASE = os.path.dirname(os.path.dirname(__file__))
sys.path.append(DIR_BASE)

# log日志输出级别
LOG_LEVEL = logging.DEBUG  # 文件
STREAM_LOG_LEVEL = logging.DEBUG  # 控制台

# excel文件的sheet页，默认读取第一个sheet页的数据，int类型，第一个sheet为0，以此类推0.....9
SHEET_ID = 0

# 报告类型不再在此定义：单一真相源是 config.ini [REPORT_TYPE]，环境变量 REPORT_TYPE 可覆盖
# （读取逻辑见 run.py 的 _report_type()）

# 是否发送钉钉消息
dd_msg = False

# 文件路径
FILE_PATH = {
    'CONFIG': os.path.join(DIR_BASE, 'conf/config.ini'),
    'LOG': os.path.join(DIR_BASE, 'logs'),
    'YAML': os.path.join(DIR_BASE),
    'TEMP': os.path.join(DIR_BASE, 'report/temp'),
    'TMR': os.path.join(DIR_BASE, 'report/tmreport'),
    'XML': os.path.join(DIR_BASE, 'data/sql'),
    'RESULTXML': os.path.join(DIR_BASE, 'report'),
    'EXCEL': os.path.join(DIR_BASE, 'data', '测试数据.xls')
}

# 默认请求头信息
LOGIN_HEADER = {
    'Content-Type': 'application/x-www-form-urlencoded;charset=UTF-8',
    'Accept': 'application/json, text/plain, */*',
    'Accept-Language': 'zh-CN,zh;q=0.9',
    'Connection': 'keep-alive'
}
