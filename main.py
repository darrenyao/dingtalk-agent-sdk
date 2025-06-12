# main.py
"""
钉钉 MCP 服务器入口
"""
import os
import sys
import asyncio
import signal
from loguru import logger

# Application specific imports

from app.dingtalk.stream_client import DingTalkStreamManager

stream_manager = DingTalkStreamManager() 

shutdown_event = asyncio.Event()


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
    # Configure logging
    configure_logging()
    # 启动钉钉流客户端
    start_stream_client()

    # Set up signal handlers
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, handle_signal)
    await shutdown_event.wait()
    await stop_stream_client()

if __name__ == "__main__":
    asyncio.run(main())