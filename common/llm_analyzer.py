from typing import Optional
from openai import OpenAI, AsyncOpenAI


class LLMAnalyzer:
    """大模型分析器，用于分析测试报错并提供修复建议"""

    def __init__(self, api_key: str, model: str, base_url: str, timeout: int = 30):
        """初始化大模型分析器

        Args:
            api_key: API密钥
            model: 模型名称
            base_url: API基础URL
            timeout: 超时时间（秒）
        """
        self.model = model
        if not api_key:
            # 未配置 API Key：降级为不可用状态，后续分析调用直接跳过，避免启动崩溃
            self.client = None
            self.async_client = None
        else:
            self.client = OpenAI(api_key=api_key, base_url=base_url, timeout=timeout)
            self.async_client = AsyncOpenAI(api_key=api_key, base_url=base_url, timeout=timeout)

    def analyze_error_sync(self, test_name: str, traceback: str) -> Optional[str]:
        """同步分析测试错误

        Args:
            test_name: 测试用例名称
            traceback: 错误堆栈信息

        Returns:
            分析结果字符串，失败返回None
        """
        try:
            if self.client is None:
                return None
            prompt = self._generate_prompt(test_name, traceback)
            completion = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {
                        "role": "user",
                        "content": prompt
                    }
                ],
                temperature=0.3,
                max_tokens=1000
            )
            return completion.choices[0].message.content
        except Exception as e:
            print(f"[LLM分析错误]: {str(e)}")
            return None

    async def analyze_error_async(self, test_name: str, traceback: str) -> Optional[str]:
        """异步分析测试错误

        Args:
            test_name: 测试用例名称
            traceback: 错误堆栈信息

        Returns:
            分析结果字符串，失败返回None
        """
        try:
            if self.client is None:
                return None
            prompt = self._generate_prompt(test_name, traceback)
            completion = await self.async_client.chat.completions.create(
                model=self.model,
                messages=[
                    {
                        "role": "user",
                        "content": prompt
                    }
                ],
                temperature=0.3,
                max_tokens=1000
            )
            return completion.choices[0].message.content
        except Exception as e:
            print(f"[LLM分析错误]: {str(e)}")
            return None

    def _generate_prompt(self, test_name: str, traceback: str) -> str:
        """生成大模型提示词

        Args:
            test_name: 测试用例名称
            traceback: 错误堆栈信息

        Returns:
            提示词字符串
        """
        return f"""
你是一位专业的Python测试工程师，擅长分析测试报错并提供修复建议。

请分析以下测试用例的错误信息，提供详细的根因分析和修复建议：

测试用例名称: {test_name}

错误堆栈信息:
{traceback}

请按照以下格式输出分析结果：
1. 根因分析：详细分析错误的根本原因
2. 修复建议：提供具体的修复方案
3. 代码示例：如果适用，提供修复后的代码示例
4. 预防措施：如何避免类似错误再次发生

请确保分析结果详细、准确、实用，帮助开发者快速定位和解决问题。
"""
