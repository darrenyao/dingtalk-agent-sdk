from datetime import timedelta
# Assuming MCPServerStreamableHttp is available alongside MCPServerStdio
# Trying the primary suggested import path first.
from agents.mcp import MCPServerStreamableHttp 
# If this were to fail in a real test environment, the alternative would be:
# from agents.mcp.http import MCPServerStreamableHttp

async def create_code_analysis_mcp():
    """创建代码分析MCP服务器"""
    mcp_server = MCPServerStreamableHttp(
        name="code_analysis_mcp",
        params={
            "timeout": timedelta(seconds=600),
            "url": "https://2d88f4b5508c4e809d9b26d95f878a4f.pre-mw-mcp.alibaba-inc.com/mcp",
            "sse_read_timeout": timedelta(seconds=600),
            "terminate_on_close": True
        },
        client_session_timeout_seconds=600.0
    )
    # The connect() method for MCPServerStreamableHttp might not be needed
    # or might be different from MCPServerStdio.
    # For now, following the pattern of MCPServerStdio's factory.
    # If MCPServerStreamableHttp doesn't have connect() or handles it internally,
    # this line would need adjustment.
    await mcp_server.connect() 
    return mcp_server

from agents import Agent
from app.config.settings import settings
from app.service.message_context import MessageContext # Assuming this agent type for now

async def create_code_analysis_agent(mcp_server: MCPServerStreamableHttp) -> Agent:
    """Creates a code analysis agent with the given MCP server."""
    
    # Placeholder instructions - actual instructions would be defined here or dynamically generated
    instructions = """
## Role: Code Analysis Assistant

You are an expert code analysis assistant. Your primary function is to analyze code snippets or entire codebases 
provided to you, identify potential issues, suggest improvements, explain complex parts, and answer questions 
related to the code's structure, functionality, and quality.

### Capabilities:
1.  **Syntax and Error Checking**: Identify syntax errors or potential runtime issues.
2.  **Best Practices**: Highlight deviations from common coding best practices (e.g., style, security, performance).
3.  **Code Explanation**: Explain what a piece of code does, its logic, and its purpose.
4.  **Refactoring Suggestions**: Offer suggestions on how to refactor code for better readability, maintainability, or efficiency.
5.  **Security Vulnerability Detection**: Point out potential security flaws (e.g., SQL injection, XSS) if applicable to the code language and context.
6.  **Documentation Generation**: Help in generating docstrings or comments for code.
7.  **Answering Questions**: Respond to specific questions about the code.

### Interaction Flow:
1.  User provides a code snippet or refers to code available to you.
2.  User asks a question, requests an analysis, or asks for suggestions.
3.  You will use your analytical capabilities and the provided MCP tools (if any specific tools are bound for code analysis) to respond.
4.  Your output should be clear, concise, and directly address the user's request. Use markdown for formatting code blocks and highlighting.

### Important Notes:
- State any assumptions you make if the provided code or context is ambiguous.
- If you use external tools or specific MCP functions, mention them if relevant to the user.
- Be prepared to handle various programming languages, but if you are not familiar with one, state it clearly.
"""

    agent = Agent[MessageContext]( # Assuming MessageContext for now, adjust if different context is needed
        name="Code Analysis Agent",
        instructions=instructions, 
        model=settings.LLM_API_MODEL, # Consider using a model specialized for code if available
        mcp_servers=[mcp_server]
    )
    return agent
