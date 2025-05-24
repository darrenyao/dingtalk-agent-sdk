from agents import Agent
from app.config.settings import settings
from agents.mcp import MCPServerStdio
from agents.run_context import RunContextWrapper
from datetime import datetime
from app.service.message_context import MessageContext
async def dynamic_instructions(context: RunContextWrapper[MessageContext], agent: Agent[MessageContext]) -> str:
    # 递归解包context，直到找到MessageContext
    ctx = context
    while hasattr(ctx, "context") and not isinstance(ctx, MessageContext):
        ctx = ctx.context

    # 直接使用当前时间
    dt = datetime.now()
    formatted_time = dt.strftime("%Y-%m-%d %H:%M:%S")

    # 构建基础用户信息部分
    user_info = (
        f"## 用户信息\n"
        f"- 当前用户名: {ctx.user_name or '未知'}\n"
        f"- 当前用户工号: {ctx.user_id or '未知'}\n"
        f"- 当前时间: {formatted_time}\n"
    )

    # 基础信息查询助理的核心指令
    core_instruction = """
## 角色
你是一个专业的基础信息查询助手，主要负责解析用户请求并提取所需的用户信息和团队数据，为后续的分析处理提供基础支持。

### 核心能力
1. **用户信息解析**：从用户输入中提取用户姓名、团队主管姓名等关键信息
2. **用户信息查询**：查询单个或多个用户的基本信息（用户ID，昵称）
3. **团队成员查询**：根据团队主管的用户ID,查询所有团队成员信息

### 工作流程指南
当收到用户请求时：
1. 解析用户输入，识别关键信息（如用户名、时间范围、团队信息等）
2. 使用合适的工具查询所需的基础信息
3. 整合查询结果，以结构化格式输出
"""

    # 工作流程示例部分
    workflow_examples = """
### 工作流程示例
**基础用户信息查询流程**:
1. 解析用户输入，识别涉及的用户名或昵称
2. 使用用户信息查询工具获取用户基本信息
3. 结构化整理用户数据并输出

**团队信息查询流程**:
1. 解析用户输入，识别团队主管名称
2. 使用用户信息查询工具获取团队主管ID
3. 使用团队成员查询工具获取所有团队成员列表
4. 结构化整理团队成员数据并输出

### 数据提取规则
1. **时间范围提取**：识别用户输入中的时间范围（如"最近一周"、"本月"等），转换为标准格式（YYYY-MM-DD）
2. **命名实体识别**：识别用户输入中的用户名、团队名等命名实体
3. **数据结构化**：将提取的信息按照后续agent所需的格式进行结构化

### 输出格式
输出结果必须是一个包含用户信息的列表，每个用户信息包含以下字段：
- nick: 用户昵称
- name: 用户姓名
- uid: 用户ID
"""

    # 组合完整的动态指令
    final_instruction = f"{user_info}\n{core_instruction}\n{workflow_examples}\n\n请根据用户输入，提取所需的用户信息和团队数据，为后续处理提供基础支持。输出必须是一个包含用户信息的列表。"
    return final_instruction

# MCP服务器创建函数
async def create_employee_info_mcp():
    mcp_server = MCPServerStdio(
        name="org_employee_mcp",
        params={
            "command": "npx",
            "args": ["-y", "@darrenyao/server-dingtalk"],
            "env": {
                "DINGTALK_APP_KEY": settings.DINGTALK_CLIENT_ID,
                "DINGTALK_APP_SECRET": settings.DINGTALK_CLIENT_SECRET
            }
        },
        client_session_timeout_seconds=600.0
    )
    await mcp_server.connect()
    return mcp_server

# Agent工厂函数
async def create_employee_info_agent(mcp_server: MCPServerStdio) -> Agent:
    # mcp_server is now passed as a parameter
    agent = Agent[MessageContext](
        name="Employee info query agent",
        instructions=dynamic_instructions,
        model=settings.LLM_API_MODEL,
        mcp_servers=[mcp_server] # Use the passed-in mcp_server
    )
    return agent
