# main.py
"""
钉钉 MCP 服务器入口
"""
import os
import sys
import asyncio
import signal
from loguru import logger
from typing import Dict # Added

# Application specific imports
from app.config.settings import settings # Added
from app.mcp.generic_mcp_server_pool import GenericMCPServerPool # Added
from app.agent.employee_agent import create_employee_info_mcp # Added
from app.agent.code_analysis_agent import create_code_analysis_mcp # Added
from app.agent.agent_manager import AgentManager # Added

from app.dingtalk.stream_client import DingTalkStreamManager

# --- Global MCP Pool Instances and Map ---
stdio_mcp_pool = GenericMCPServerPool(
    pool_name="stdio",
    pool_size=settings.STDIO_MCP_POOL_SIZE,
    server_factory=create_employee_info_mcp
)

code_analysis_mcp_pool = GenericMCPServerPool(
    pool_name="code_analysis",
    pool_size=settings.CODE_ANALYSIS_MCP_POOL_SIZE,
    server_factory=create_code_analysis_mcp
)

mcp_pools_map: Dict[str, GenericMCPServerPool] = {
    "stdio": stdio_mcp_pool,
    "code_analysis": code_analysis_mcp_pool,
}
# --- End Global MCP Pool Instances ---


stream_manager = DingTalkStreamManager() # Existing
# It's unclear if stream_manager needs agent_manager. If so, its instantiation might need to be deferred
# or agent_manager passed to it. For now, agent_manager is created in main().

shutdown_event = asyncio.Event()

# AgentManager instance - will be created in main() after pools are initialized.
# If AgentManager needs to be accessed by components initialized before main()'s try block,
# this might need adjustment (e.g. global but None, then initialized).
agent_manager_instance: AgentManager = None 

def configure_logging():
    """Configure logging with enhanced settings"""
    # Remove default handler
    logger.remove()
    
    # Add colored console handler with better formatting
    logger.add(
        sys.stderr,
        format="<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>",
        level="INFO"
    )
    
    # Add file handler for persistent logs
    log_dir = "logs"
    os.makedirs(log_dir, exist_ok=True)
    logger.add(
        os.path.join(log_dir, "app_{time:YYYY-MM-DD}.log"),
        rotation="12:00",  # New file at noon
        retention="7 days",  # Keep logs for 7 days
        compression="zip",  # Compress old log files
        level="DEBUG"
    )


def start_stream_client():
    """启动钉钉流客户端"""
    try:
        stream_manager.start()
        logger.info("Stream 网关连接成功")
    except Exception as e:
        logger.error(f"钉钉流客户端启动失败: {str(e)}")
        raise

def handle_signal():
    shutdown_event.set()

async def stop_stream_client():
    """停止钉钉流客户端"""
    try:
        stream_manager.stop()
        logger.info("钉钉流客户端停止成功")
    except Exception as e:
        logger.error(f"钉钉流客户端停止失败: {str(e)}")


async def main():
    """Main function to run the DingTalk message processor"""
    global agent_manager_instance # To assign the created instance

    # Configure logging
    configure_logging()

    try:
        # Startup phase: Initialize MCP pools
        logger.info("Application startup: Initializing MCP pools...")
        await stdio_mcp_pool.initialize()
        logger.info("Stdio MCP pool initialized.")
        await code_analysis_mcp_pool.initialize()
        logger.info("Code Analysis MCP pool initialized.")
        
        # Instantiate AgentManager with the initialized pools
        # Note: stream_manager is instantiated globally. If it needs agent_manager,
        # this architecture might need refinement (e.g., pass agent_manager to stream_manager.start()
        # or lazy initialization within stream_manager).
        agent_manager_instance = AgentManager(mcp_pools=mcp_pools_map)
        logger.info("AgentManager initialized with MCP pools.")
        # TODO: Pass agent_manager_instance to DingTalkStreamManager if it needs to use it.
        # Example: stream_manager.set_agent_manager(agent_manager_instance) or pass to methods.

        # 启动钉钉流客户端 (Existing)
        start_stream_client()

        # Set up signal handlers (Existing)
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, handle_signal)
        
        logger.info("Application started successfully. Waiting for shutdown signal...")
        await shutdown_event.wait()

    except Exception as e:
        logger.error(f"Critical error during application startup or main loop: {e}", exc_info=True)
        # Depending on the error, we might still want to attempt cleanup.
    finally:
        logger.info("Application shutdown initiated...")
        
        # Stop DingTalk stream client first
        await stop_stream_client()
        
        # Shutdown MCP pools
        logger.info("Shutting down MCP pools...")
        try:
            await stdio_mcp_pool.shutdown()
            logger.info("Stdio MCP pool shut down.")
        except Exception as e:
            logger.error(f"Error during Stdio MCP pool shutdown: {e}", exc_info=True)
        
        try:
            await code_analysis_mcp_pool.shutdown()
            logger.info("Code Analysis MCP pool shut down.")
        except Exception as e:
            logger.error(f"Error during Code Analysis MCP pool shutdown: {e}", exc_info=True)
        
        logger.info("Application shutdown complete.")

if __name__ == "__main__":
    asyncio.run(main())