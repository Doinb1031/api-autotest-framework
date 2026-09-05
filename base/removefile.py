import os

from pythonproject.common.recordlog import logs


def remove_file(filepath, endlst):
    """
    删除指定目录下特定后缀的文件。

    遍历 filepath 目录下的所有文件，如果文件名以 endlst 中任一后缀结尾则删除。
    如果目录不存在则自动创建。

    :param filepath: 目录路径，如 './report/temp'
    :param endlst: 要删除的文件后缀列表，如 ['json', 'txt', 'attach']
    :return: None
    """
    try:
        if os.path.exists(filepath):
            # 获取该目录下所有文件名称
            dir_lst_files = os.listdir(filepath)
            for file_name in dir_lst_files:
                # 拼接完整文件路径（Windows 路径分隔符）
                fpath = filepath + '\\' + file_name
                # 检查 endlst 必须是列表类型
                if isinstance(endlst, list):
                    for ft in endlst:
                        # endswith 判断文件名是否以指定后缀结尾
                        if file_name.endswith(ft):
                            os.remove(fpath)
                else:
                    raise TypeError('file Type error,must is list')
        else:
            # 目录不存在则创建
            os.makedirs(filepath)
    except Exception as e:
        logs.error(e)


def remove_directory(path):
    """
    删除目录（注意：此函数有 bug,os.remove 只能删除文件，不能删除目录）。

    :param path: 要删除的目录路径
    :return: None
    """
    try:
        if os.path.exists(path):
            # BUG: os.remove 只能删除文件，删除目录会报 PermissionError
            # 应改为 os.rmdir(path) 或 shutil.rmtree(path)
            os.remove(path)
    except Exception as e:
        logs.error(e)
