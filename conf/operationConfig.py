import sys
import traceback

# sys.path.insert(0, "..")

import configparser

from common.recordlog import logs
from conf import setting


class OperationConfig:
    """
    封装 configparser 的 INI 配置文件读写类。

    本类用于统一读取和写入项目中的 *.ini 配置文件（默认读取 setting.FILE_PATH['CONFIG']）。
    框架中的数据库连接、报告类型、邮件、SSH 等环境配置均通过此类获取。
    """

    def __init__(self, filepath=None):
        """
        初始化 OperationConfig 实例，加载 ini 配置文件。

        :param filepath: 可选，ini 文件绝对路径。默认为 None，
                         此时使用 setting.FILE_PATH['CONFIG'] 中定义的配置文件路径。
        """
        # 如果没有传入路径，则使用 setting.py 中配置的默认 config.ini 路径
        if filepath is None:
            self.__filepath = setting.FILE_PATH['CONFIG']
        else:
            self.__filepath = filepath

        # 创建 ConfigParser 解析器对象
        self.conf = configparser.ConfigParser()

        # 尝试读取配置文件，失败时记录错误日志
        try:
            self.conf.read(self.__filepath, encoding='utf-8')
        except Exception as e:
            # 获取当前异常信息对象并打印异常堆栈
            exc_type, exc_value, exc_obj = sys.exc_info()
            logs.error(str(traceback.print_exc(exc_obj)))

        # 初始化时自动读取 REPORT_TYPE 配置项，保存到 self.type，方便外部直接访问
        self.type = self.get_report_type('type')

    def get_item_value(self, section_name):
        """
        获取指定 section 下的所有配置项，并以字典形式返回。

        :param section_name: ini 文件中的 section 名称（即头部值）
        :return: dict,key 为 option,value 为对应配置值
        """
        items = self.conf.items(section_name)
        return dict(items)

    def get_section_for_data(self, section, option):
        """
        获取指定 section 下某个 option 的配置值。

        :param section: ini 文件中的 section 名称
        :param option: section 下的具体选项名
        :return: 对应的配置字符串；若读取异常则返回空字符串并记录错误日志
        """
        try:
            values = self.conf.get(section, option)
            return values
        except Exception as e:
            logs.error(str(traceback.format_exc()))
            return ''

    def write_config_data(self, section, option_key, option_value):
        """
        向 ini 配置文件中写入数据。

        注意：只有当 section 不存在时才会新增并写入；如果 section 已存在，
        则仅打印日志提示写入失败，不会更新已有 section 中的内容。

        :param section: 要新增的 section 名称
        :param option_key: section 下的选项名
        :param option_value: 选项对应的值
        :return: None
        """
        if section not in self.conf.sections(): 
            # section 不存在时新增，并设置键值对
            self.conf.add_section(section)
            self.conf.set(section, option_key, option_value)
        else:
            # section 已存在则不再覆盖，避免误改已有配置
            logs.info('"%s"值已存在，写入失败' % section)

        # 将内存中的配置回写到 ini 文件
        with open(self.__filepath, 'w', encoding='utf-8') as f:
            self.conf.write(f)

    def get_section_mysql(self, option):
        """读取 [MYSQL] 节下的指定配置项。"""
        return self.get_section_for_data("MYSQL", option)

    def get_section_redis(self, option):
        """读取 [REDIS] 节下的指定配置项。"""
        return self.get_section_for_data("REDIS", option)

    def get_section_clickhouse(self, option):
        """读取 [CLICKHOUSE] 节下的指定配置项。"""
        return self.get_section_for_data("CLICKHOUSE", option)

    def get_section_mongodb(self, option):
        """读取 [MongoDB] 节下的指定配置项。"""
        return self.get_section_for_data("MongoDB", option)

    def get_report_type(self, option):
        """读取 [REPORT_TYPE] 节下的指定配置项，例如报告类型。"""
        return self.get_section_for_data('REPORT_TYPE', option)

    def get_section_ssh(self, option):
        """读取 [SSH] 节下的指定配置项。"""
        return self.get_section_for_data("SSH", option)

    def get_section_http(self, option):
        """读取 [HTTP] 节下的指定配置项（超时/重试/连接池/TLS 校验）。"""
        return self.get_section_for_data("HTTP", option)

    def get_section_sqlite(self, option):
        """读取 [SQLITE] 节下的指定配置项（db 断言用的 SQLite 库文件路径）。"""
        return self.get_section_for_data("SQLITE", option)