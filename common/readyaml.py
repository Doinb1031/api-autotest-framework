import yaml
import traceback

from yaml.scanner import ScannerError

from common import context
from common.recordlog import logs


def get_testcase_yaml(file):
    testcase_list = []
    try:
        with open(file, 'r', encoding='utf-8') as f:
            data = yaml.safe_load(f)
            if len(data) <= 1:
                yam_data = data[0]
                base_info = yam_data.get('baseInfo')
                for ts in yam_data.get('testCase'):
                    param = [base_info, ts]
                    testcase_list.append(param)
                return testcase_list
            else:
                return data
    except UnicodeDecodeError:
        logs.error(f"[{file}]文件编码格式错误，--尝试使用utf-8编码解码YAML文件时发生了错误，请确保你的yaml文件是UTF-8格式！")
    except FileNotFoundError:
        logs.error(f'[{file}]文件未找到，请检查路径是否正确')
    except Exception as e:
        logs.error(f'获取【{file}】文件数据时出现未知错误: {str(e)}')


class ReadYamlData:
    """YAML 测试数据读写类

    用于读取 YAML 格式的接口测试用例文件，
    以及管理接口关联提取变量（存储于 common/context.py 的内存业务上下文，不再落盘）。
    - get_yaml_data: 解析 YAML 测试用例文件
    - write_yaml_data: 向内存上下文写入接口提取值
    - get_extract_yaml: 读取内存上下文中的提取变量
    - clear_yaml_data: 清空内存上下文
    - get_method / get_request_parame: 快捷获取请求方法和参数
    """

    def __init__(self, yaml_file=None):
        if yaml_file is not None:
            self.yaml_file = yaml_file
        else:
            pass
        self.yaml_data = None

    def get_yaml_data(self):
        """
        获取测试用例yaml数据
        :param file: YAML文件
        :return: 返回list
        """
        # Loader=yaml.FullLoader表示加载完整的YAML语言，避免任意代码执行，无此参数控制台报Warning
        try:
            with open(self.yaml_file, 'r', encoding='utf-8') as f:
                self.yaml_data = yaml.safe_load(f)
                return self.yaml_data
        except Exception:
            logs.error(str(traceback.format_exc()))

    def write_yaml_data(self, value):
        """
        写入接口提取值到内存业务上下文，用于接口间参数传递。
        同 key 后写覆盖先写。

        :param value: 写入数据，必须用 dict
        """
        context.set_vars(value)

    def clear_yaml_data(self):
        """清空内存业务上下文（session 前置调用，保证每次运行业务数据从零开始）"""
        context.clear()

    def get_extract_yaml(self, node_name, second_node_name=None):
        """
        用于读取接口提取的变量值（来自内存业务上下文）

        :param node_name: 一级节点名，即变量名
        :param second_node_name: 二级节点名，可选，用于获取嵌套变量值
        :return: 返回变量值，或嵌套变量值的dict；变量不存在时返回 None
        """
        return context.get_var(node_name, second_node_name)

    def get_testCase_baseInfo(self, case_info):
        """
        获取testcase yaml文件的baseInfo数据
        :param case_info: yaml数据，dict类型
        :return: baseInfo数据，dict类型
        """
        pass

    def get_method(self):
        """
        :param self:
        :return:
        """
        yal_data = self.get_yaml_data()
        metd = yal_data[0].get('method')
        return metd

    def get_request_parame(self):
        """
        获取yaml测试数据中的请求参数
        :return: 返回请求参数的list，每个元素为一个dict，包含请求参数的key-value对
        """
        data_list = []
        yaml_data = self.get_yaml_data()
        del yaml_data[0]
        for da in yaml_data:
            data_list.append(da)
        return data_list
