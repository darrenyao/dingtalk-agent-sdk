import json
import asyncio
import time
from typing import Any, Dict, Tuple

from dingtalk_stream import GraphRequest, CallbackMessage, AckMessage
from dingtalk_stream.frames import Headers
from dingtalk_stream.graph import GraphHandler, GraphResponse
from loguru import logger

from app.utils.stop_watch import Stopwatch
from app.service.message_context import MessageContext
from app.agent.agent_manager import AgentManager


class MessageCallbackHandler(GraphHandler):
    def __init__(self, timeout: int = 120):
        """
        Initialize the handler with a message processor
        
        Args:
            timeout: 处理超时时间（秒）
        """
        super().__init__()
        self.timeout = timeout
        self.processing_lock = asyncio.Lock()  # ✅ 添加并发控制
        
        self.stats = {
            "messages_received": 0,
            "messages_processed": 0,
            "errors": 0,
            "timeouts": 0,
            "last_message_time": 0,
        }

    def pre_start(self):
        """Optional: Called before the handler starts"""
        pass

    async def process(self, callback: CallbackMessage):
        """
        Process DingTalk stream message
        简化处理流程，直接在这里完成所有逻辑
        """
        try:
            # Parse incoming message
            graph_request = GraphRequest.from_dict(callback.data)
            logger.info(f"Processing message: {graph_request.body}")

            # Extract message content and metadata
            text_content, message_metadata = self._parse_message_content(graph_request.body)

            # Skip empty messages
            if not text_content:
                logger.info("Received empty message, skipping processing")
                return self._create_empty_response()  # ✅ 直接返回
            
            # Update stats
            self.stats["messages_received"] += 1
            self.stats["last_message_time"] = time.time()

            # 使用锁防止并发处理
            async with self.processing_lock:
                try:
                    # Create stop watch for timing
                    stop_watch = Stopwatch()
                    stop_watch.start()

                    # Construct MessageContext
                    context = MessageContext(
                        content=text_content,
                        user_name=message_metadata["sender_nick"],
                        user_id=message_metadata["sender_id"],
                        sender_union_id=message_metadata["sender_union_id"],
                        is_group_chat=message_metadata["conversation_type"] != "1",
                        group_name=message_metadata["group_name"],
                        conversation_id=message_metadata["conversation_id"],
                        timestamp=int(time.time()),
                        conversation_token=message_metadata["conversation_token"]
                    )

                    # 处理消息，添加超时控制
                    result = await asyncio.wait_for(
                        self._process_with_agent_manager(context),
                        timeout=self.timeout
                    )
                    
                    # Update success stats
                    self.stats["messages_processed"] += 1
                    logger.info(
                        f"Finished processing message for {context.user_name}, result: {result}"
                        f"elapsed: {stop_watch.elapsed():.2f}ms"
                    )
                    
                    return self._create_response(result)  # ✅ 直接返回
                    
                except asyncio.TimeoutError:
                    self.stats["timeouts"] += 1
                    logger.error(f"Message processing timeout after {self.timeout}s")
                    return self._create_error_response("Processing timeout")  # ✅ 直接返回
                    
                except Exception as e:
                    self.stats["errors"] += 1
                    logger.error(f"Error processing message: {str(e)}", exc_info=True)
                    return self._create_error_response(str(e))  # ✅ 直接返回

        except Exception as e:
            self.stats["errors"] += 1
            logger.error(f"Error parsing callback message: {str(e)}", exc_info=True)
            return self._create_error_response(f"Parse error: {str(e)}")  # ✅ 直接返回

    async def _process_with_agent_manager(self, context: MessageContext) -> Dict[str, Any]:
        """
        使用 AgentManager 处理消息
        简化版本，专注于核心逻辑
        """
        agent_manager = None
        try:
            logger.info(
                f"Processing message from {context.user_name} ({context.user_id}) "
                f"in {'group' if context.is_group_chat else 'private'} chat"
            )

            # 创建 AgentManager 实例
            agent_manager = AgentManager(current_user_info=context.to_dict())
            
            # 处理消息，内部添加超时控制
            result = await asyncio.wait_for(
                agent_manager.process_message(context),
                timeout=self.timeout - 5  # 预留5秒给清理
            )
            
            return result.final_output

        except asyncio.TimeoutError:
            logger.error(f"AgentManager processing timeout for user {context.user_name}")
            raise  # 重新抛出，由上层处理
            
        except Exception as e:
            logger.error(f"Error in agent manager processing: {str(e)}", exc_info=True)
            return {
                "status": "error",
                "message": str(e),
                "error_type": type(e).__name__
            }
        finally:
            # 确保资源清理
            if agent_manager:
                try:
                    await asyncio.wait_for(agent_manager.cleanup(), timeout=5)
                except Exception as cleanup_error:
                    logger.warning(f"Error during cleanup: {cleanup_error}")

    def _create_response(self, result: Any) -> Tuple[int, Dict]:
        """根据结果类型创建适当的响应"""
        if not result:
            return self._create_empty_response()

        response = self._create_base_response()

        if isinstance(result, dict) and "tool_name" in result:
            response.body = self._create_tool_response(result)
        else:
            response.body = self._create_text_response(result)

        logger.info(f"Response: {response.to_dict()}")

        return AckMessage.STATUS_OK, response.to_dict()
    
    def _create_base_response(self) -> GraphResponse:
        """创建带有通用设置的基础响应"""
        response = GraphResponse()
        response.status_line.code = 200
        response.status_line.reason_phrase = "OK"
        response.headers["Content-Type"] = "application/json"
        return response

    def _create_tool_response(self, result: Dict) -> Dict:
        """创建工具执行结果的响应"""
        return {
            "tool_name": result["tool_name"],
            "tool_args": result["tool_args"],
            "tool_output": self._make_json_serializable(result["tool_output"]),
            "text": result["summary"]
        }

    def _create_text_response(self, result: Any) -> Dict:
        """创建文本内容的响应"""
        if hasattr(result, "text") and hasattr(result, "type"):
            return {"content": result.text}
        return {"content": self._make_json_serializable(result)}

    def _create_empty_response(self) -> Tuple[int, Dict]:
        """创建空消息的响应"""
        response = self._create_base_response()
        response.body = {"status": "empty_message", "text": "No valid text content"}
        return AckMessage.STATUS_OK, response.to_dict()

    def _create_error_response(self, error_message: str) -> Tuple[int, Dict]:
        """创建错误响应"""
        response = self._create_base_response()
        response.status_line.code = 500
        response.status_line.reason_phrase = "Internal Server Error"
        response.body = {"error": error_message}
        return AckMessage.STATUS_SYSTEM_EXCEPTION, response.to_dict()

    def _parse_message_content(self, body: Any) -> Tuple[str, Dict[str, Any]]:
        """Parse message content and extract metadata"""
        try:
            # Parse body if it's a string
            if isinstance(body, str):
                body = json.loads(body)

            # Extract text content
            text_content = body.get("input", "").strip()
            
            # Extract org_id from multiple possible locations
            org_id = body.get("orgId") or body.get("org_id")
            request_id = None
            if not org_id:
                scenario_ctx = body.get("scenarioContext")
                if scenario_ctx:
                    try:
                        if isinstance(scenario_ctx, str):
                            scenario_ctx_obj = json.loads(scenario_ctx)
                        else:
                            scenario_ctx_obj = scenario_ctx
                        org_id = scenario_ctx_obj.get("orgId")
                        request_id = scenario_ctx_obj.get("requestId")
                    except Exception as e:
                        logger.warning(f"Failed to parse scenarioContext for orgId: {e}")

            # Extract metadata
            metadata = {
                "sender_id": body.get("sender_id", ""),
                "sender_nick": body.get("sender_nick", "Unknown User"),
                "conversation_id": body.get("conversation_id", ""),
                "conversation_type": body.get("conversation_type", "1"),
                "group_name": body.get("conversation_title", ""),
                "conversation_token": body.get("conversationToken", ""),
                "sender_union_id": body.get("sender_union_id", ""),
                "request_id": request_id
            }

            return text_content, metadata

        except Exception as e:
            logger.warning(f"Failed to parse message content: {e}")
            return "", {}
    
    async def raw_process(self, callback: CallbackMessage):
        """
        Process a message from DingTalk stream and return an AckMessage
        This method follows the dingtalk_stream library's expected behavior
        """
        code, response_dict = await self.process(callback)
        ack_message = AckMessage()
        ack_message.code = code
        ack_message.headers.message_id = callback.headers.message_id
        ack_message.headers.content_type = Headers.CONTENT_TYPE_APPLICATION_JSON
        ack_message.data = {"response": response_dict}
        return ack_message


    def get_stats(self) -> Dict[str, Any]:
        """Get handler statistics"""
        return self.stats.copy()

    def reset_stats(self) -> None:
        """Reset all statistics counters except last_message_time"""
        self.stats.update({
            "messages_received": 0, 
            "messages_processed": 0, 
            "errors": 0,
            "timeouts": 0
        })

    def _make_json_serializable(self, obj):
        """将对象转换为可 JSON 序列化的形式"""
        if obj is None:
            return None
        elif isinstance(obj, (str, int, float, bool)):
            return obj
        elif isinstance(obj, (list, tuple)):
            return [self._make_json_serializable(item) for item in obj]
        elif isinstance(obj, dict):
            return {k: self._make_json_serializable(v) for k, v in obj.items()}
        elif hasattr(obj, "text") and hasattr(obj, "type"):
            # 处理 TextContent 类型
            return obj.text
        elif hasattr(obj, "__dict__"):
            # 尝试将对象转换为字典
            return self._make_json_serializable(obj.__dict__)
        else:
            # 其他类型转换为字符串
            return str(obj)