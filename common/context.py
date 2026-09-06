"""
进程级业务上下文：接口间传递的提取变量（goodsIds、orderNumber 等）保存在内存中。

这是真实工作主流的做法——同一次运行内，变量沿调用链在内存中传递
（对应 JMeter 的线程变量表、httprunner 的 extract/export、Postman 的运行时环境变量），
随运行结束销毁，不再落盘到 extract.yaml。

读写语义与原 extract.yaml 文件方案保持一致：
- write：同 key 后写覆盖先写
- get：变量不存在时记录日志并返回 None（调用方以 None 判断缺失）
"""
import threading

from common.recordlog import logs

_lock = threading.Lock()
_store = {}


def set_vars(data):
    """批量写入提取变量，data 必须为 dict，同 key 后写覆盖先写。"""
    if not isinstance(data, dict):
        logs.info('写入[业务上下文]的数据必须为dict格式')
        return
    with _lock:
        _store.update(data)


def get_var(node_name, second_node_name=None):
    """
    读取提取变量。

    :param node_name: 变量名
    :param second_node_name: 可选，嵌套取值：dict 按 key 取
    :return: 变量值；变量不存在时记录日志并返回 None
    """
    with _lock:
        value = _store.get(node_name)
    if value is None:
        logs.error(f"【业务上下文】没有找到变量：{node_name}")
        return None
    if second_node_name is not None:
        try:
            return value[second_node_name]
        except Exception as e:
            logs.error(f"【业务上下文】变量 {node_name} 中没有找到：{second_node_name},--%s" % e)
            return None
    return value


def clear():
    """清空上下文（session 前置调用，保证每次运行业务数据从零开始）。"""
    with _lock:
        _store.clear()


def snapshot():
    """返回当前上下文的副本，便于调试时查看全部已提取变量。"""
    with _lock:
        return dict(_store)
