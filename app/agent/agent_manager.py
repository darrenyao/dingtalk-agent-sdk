"""
Agent manager for handling different types of agents
"""
from typing import Dict, Any, Optional, List, TypedDict
from typing_extensions import NotRequired
from loguru import logger
from app.agent.employee_agent import create_employee_info_agent
from openai import AsyncOpenAI

from agents import (
    
    Runner,set_default_openai_client, set_default_openai_api, set_tracing_disabled
    
)

from app.config.settings import settings
from app.service.message_context import MessageContext
from app.mcp.mcp_server_stdio_pool import MCPServerStdioPool # Assuming this path

class AgentManager:
    def __init__(self, mcp_server_pool: MCPServerStdioPool, current_user_info: Optional[Dict[str, Any]] = None):
        self.current_user_info = current_user_info or {}
        self.mcp_server_pool = mcp_server_pool
        self.agent = None
        self.client = None
        self._setup_llm_client()
        logger.info(f"初始化 AgentManager，用户信息: {self.current_user_info}")

    def _setup_llm_client(self):
        """设置 LLM 客户端和全局配置"""
        try:
            base_url = settings.LLM_API_BASE_URL
            api_key = settings.LLM_API_KEY
            
            if not base_url or not api_key:
                raise ValueError("Please set LLM_API_BASE_URL and LLM_API_KEY")
            
            self.client = AsyncOpenAI(
                base_url=base_url,
                api_key=api_key
            )
            set_default_openai_client(client=self.client, use_for_tracing=False)
            set_default_openai_api("chat_completions")
            set_tracing_disabled(disabled=True)
            logger.info(" LLM Client 设置成功")
        except Exception as e:
            logger.error(f"LLM Client 设置失败: {str(e)}", exc_info=True)
            raise


    async def cleanup(self):
        """清理资源"""
        try:
            # MCP Server cleanup is now handled by the pool
            # Ensure agent and client are reset
            self.agent = None
            self.client = None
            logger.info("AgentManager resources (agent and client) have been cleaned up. MCP server cleanup is managed by the pool.")
        except Exception as e:
            logger.error(f"清理资源失败: {str(e)}", exc_info=True)
            raise


    async def process_message(self, context: MessageContext) -> str:
        """处理消息"""
        acquired_mcp_server = None
        try:
            logger.info(f"收到消息: {context.content}")
            
            acquired_mcp_server = await self.mcp_server_pool.acquire()
            # agent 执行逻辑
            self.agent = await create_employee_info_agent(mcp_server=acquired_mcp_server)

            result = await Runner.run(self.agent, context.content, context=context)
            
            logger.info(f"\n\nFinal response:\n{result.final_output}")

            return result
        except Exception as e:
            logger.error(f"处理消息失败: {str(e)}", exc_info=True)
            return f"处理消息时出错: {str(e)}"
        finally:
            if acquired_mcp_server:
                await self.mcp_server_pool.release(acquired_mcp_server)
