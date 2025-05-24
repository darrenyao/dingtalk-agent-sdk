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
# Update import from MCPServerStdioPool to GenericMCPServerPool
from app.mcp.generic_mcp_server_pool import GenericMCPServerPool
from typing import Dict, Any, Optional # Ensure Dict is imported

class AgentManager:
    def __init__(self, mcp_pools: Dict[str, GenericMCPServerPool], current_user_info: Optional[Dict[str, Any]] = None):
        self.current_user_info = current_user_info or {}
        self.mcp_pools = mcp_pools # Store the dictionary of pools
        self.agent = None
        self.client = None
        self._setup_llm_client()
        logger.info(f"初始化 AgentManager，用户信息: {self.current_user_info}, MCP Pools: {list(mcp_pools.keys()) if mcp_pools else 'None'}")

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
        selected_pool: Optional[GenericMCPServerPool] = None
        healthy_server = True # Assume server is healthy unless an exception occurs

        try:
            logger.info(f"收到消息: {context.content}")

            # Pool Selection (Hardcoded to "stdio" for now)
            pool_key = "stdio"
            selected_pool = self.mcp_pools.get(pool_key)

            if selected_pool is None:
                error_msg = f"Configuration error: MCP pool '{pool_key}' not found."
                logger.error(error_msg)
                # Depending on desired behavior, either raise an exception or return error message
                # For now, returning an error message as per example
                return error_msg
            
            logger.info(f"Using MCP pool: {pool_key}")
            acquired_mcp_server = await selected_pool.acquire()
            
            # Agent Creation (Hardcoded to create_employee_info_agent for "stdio" pool)
            # Future: Add logic to select agent creation function based on pool_key
            if pool_key == "stdio":
                self.agent = await create_employee_info_agent(mcp_server=acquired_mcp_server)
            # elif pool_key == "code_analysis":
                # self.agent = await create_code_analysis_agent(mcp_server=acquired_mcp_server) # Placeholder
            else:
                # This case should ideally be caught by pool_key check or have a default
                error_msg = f"Runtime error: No agent creation logic for pool key '{pool_key}'."
                logger.error(error_msg)
                healthy_server = False # Mark server potentially problematic due to logic error
                return error_msg

            result = await Runner.run(self.agent, context.content, context=context)
            
            logger.info(f"\n\nFinal response:\n{result.final_output}")
            return result
        except Exception as e:
            logger.error(f"处理消息失败: {str(e)}", exc_info=True)
            healthy_server = False # Server encountered an exception during processing
            return f"处理消息时出错: {str(e)}"
        finally:
            if acquired_mcp_server and selected_pool:
                logger.debug(f"Releasing MCP server to pool '{pool_key}'. Healthy: {healthy_server}")
                await selected_pool.release(acquired_mcp_server, is_healthy=healthy_server)
            elif acquired_mcp_server and not selected_pool:
                # This case should ideally not be reached if selected_pool check is robust
                logger.error("Acquired MCP server but selected_pool is None in finally block. Cannot release.")
