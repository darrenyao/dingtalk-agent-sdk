import os

from dotenv import load_dotenv

load_dotenv()

class Settings:
    """Application settings"""

    # DingTalk API configuration
    # For Stream API (WebSocket)
    DINGTALK_CLIENT_ID = os.getenv("DINGTALK_CLIENT_ID", "")
    DINGTALK_CLIENT_SECRET = os.getenv("DINGTALK_CLIENT_SECRET", "")
    DINGTALK_STREAM_TOPIC = os.getenv("DINGTALK_STREAM_TOPIC", "/v1.0/graph/api/invoke")

    # CARD TEMPLATE ID
    DINGTALK_CARD_TEMPLATE_ID = os.getenv("DINGTALK_CARD_TEMPLATE_ID", "9c178dc6-57e9-4952-afbf-77bc4efbf21c.schema")

    # LLM API configuration
    LLM_API_KEY = os.getenv("LLM_API_KEY", "")
    LLM_API_BASE_URL = os.getenv("LLM_API_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1")
    LLM_API_MODEL = os.getenv("LLM_API_MODEL", "qwen-plus")


settings = Settings()