import asyncio
from loguru import logger
from typing import List, Optional
# Assuming 'agents.mcp.MCPServerStdio' is the correct path.
# If 'agents' is a top-level directory in the project, this should work.
# If 'agents' is a library installed elsewhere, the import might need adjustment
# based on how it's structured and installed.
from agents.mcp import MCPServerStdio
from app.agent.employee_agent import create_employee_info_mcp
from app.config.settings import settings # Import application settings

class MCPServerStdioPool:
    def __init__(self, pool_size: Optional[int] = None):
        """
        Initializes the MCP Server Stdio Pool.

        Args:
            pool_size: The maximum number of MCPServerStdio instances to manage.
                       If None, defaults to settings.MCP_SERVER_POOL_SIZE.
        """
        resolved_pool_size: int
        if pool_size is None:
            resolved_pool_size = settings.MCP_SERVER_POOL_SIZE
            logger.info(f"Pool size not provided, using default from settings: {resolved_pool_size}")
        else:
            resolved_pool_size = pool_size
            logger.info(f"Pool size provided: {resolved_pool_size}")

        if resolved_pool_size <= 0:
            raise ValueError("Pool size must be positive.")
        
        self.pool_size: int = resolved_pool_size
        self.available_servers: asyncio.Queue[MCPServerStdio] = asyncio.Queue(maxsize=self.pool_size)
        self.all_servers: List[MCPServerStdio] = []
        logger.info(f"MCPServerStdioPool initialized with effective size: {self.pool_size}")

    async def initialize(self):
        """
        Creates and initializes the MCPServerStdio instances for the pool.
        If any server fails to initialize, an exception is raised.
        """
        logger.info(f"Initializing MCPServerStdioPool with {self.pool_size} servers...")
        for i in range(self.pool_size):
            server_id = i + 1
            logger.info(f"Attempting to create and connect server {server_id}/{self.pool_size}...")
            try:
                mcp_server = await create_employee_info_mcp()
                # create_employee_info_mcp should ideally handle its own connection logging.
                # If not, add await mcp_server.connect() here if create_employee_info_mcp doesn't.
                # Based on previous subtask, create_employee_info_mcp already connects.
                
                self.available_servers.put_nowait(mcp_server)
                self.all_servers.append(mcp_server)
                logger.info(f"Successfully created and connected server {server_id}/{self.pool_size} (Name: {mcp_server.name}) and added to pool.")
            except Exception as e:
                logger.error(f"Failed to create or connect server {server_id}/{self.pool_size}: {e}", exc_info=True)
                # As per instructions, re-raise to halt further initialization.
                # Perform partial cleanup of already initialized servers before re-raising.
                logger.warning(f"Initialization failed. Shutting down {len(self.all_servers)} already initialized servers before exiting.")
                for srv in self.all_servers:
                    try:
                        await srv.cleanup()
                        logger.info(f"Cleaned up server {srv.name} during partial shutdown.")
                    except Exception as cleanup_exc:
                        logger.error(f"Error cleaning up server {srv.name} during partial shutdown: {cleanup_exc}", exc_info=True)
                self.all_servers.clear() # Clear the list as they are now cleaned up
                # Empty the queue as well
                while not self.available_servers.empty():
                    try:
                        self.available_servers.get_nowait()
                    except asyncio.QueueEmpty:
                        break
                raise  # Re-raise the original exception
        
        logger.info(f"MCPServerStdioPool initialization complete. {len(self.all_servers)} servers ready.")

    async def acquire(self) -> MCPServerStdio:
        """
        Acquires an available MCPServerStdio instance from the pool.
        Waits if no server is currently available.

        Returns:
            An MCPServerStdio instance.
        """
        logger.debug("Attempting to acquire an MCP server from the pool...")
        server = await self.available_servers.get()
        logger.info(f"MCP server (Name: {server.name}) acquired from the pool. Queue size: {self.available_servers.qsize()}")
        return server

    async def release(self, server: MCPServerStdio, is_healthy: bool = True):
        """
        Releases an MCPServerStdio instance back to the pool or cleans it up if unhealthy.

        Args:
            server: The MCPServerStdio instance to release.
            is_healthy: True if the server is considered healthy and can be reused,
                        False if it's unhealthy and should be cleaned up and removed.
        """
        if server is None:
            logger.warning("Attempted to release a None server. Ignoring.")
            return

        if is_healthy:
            logger.debug(f"Attempting to release healthy MCP server (Name: {server.name}) back to the pool...")
            try:
                await self.available_servers.put(server)
                logger.info(f"Healthy MCP server (Name: {server.name}) released back to the pool. Queue size: {self.available_servers.qsize()}")
            except asyncio.QueueFull:
                logger.error(f"Failed to release healthy server {server.name}: Pool queue is unexpectedly full. This might indicate a logic error or a server was released that wasn't acquired from this pool.", exc_info=True)
                # If the queue is full, it's a problematic state.
                # We might want to clean up this server directly if it can't be re-added.
                logger.warning(f"Cleaning up server {server.name} directly as it could not be returned to the full pool (was healthy but queue full).")
                try:
                    await server.cleanup()
                    # Also remove from all_servers if we clean it up here
                    if server in self.all_servers:
                        self.all_servers.remove(server)
                        logger.info(f"Server {server.name} removed from all_servers after cleanup due to full queue.")
                except Exception as e:
                    logger.error(f"Error during direct cleanup of server {server.name} that couldn't be released (healthy but queue full): {e}", exc_info=True)
        else:
            logger.warning(f"Processing unhealthy MCP server (Name: {server.name}). It will be cleaned up and removed from the pool.")
            try:
                await server.cleanup()
                logger.info(f"Successfully cleaned up unhealthy server (Name: {server.name}).")
            except Exception as e:
                logger.error(f"Error during cleanup of unhealthy server (Name: {server.name}): {e}", exc_info=True)
            finally:
                if server in self.all_servers:
                    self.all_servers.remove(server)
                    logger.info(f"Unhealthy server (Name: {server.name}) removed from all_servers list. Current all_servers count: {len(self.all_servers)}")
                else:
                    logger.warning(f"Unhealthy server (Name: {server.name}) was not found in all_servers list for removal. This might indicate a double release or prior removal.")
                # Note: No replenishment logic in this subtask.

    async def shutdown(self):
        """
        Shuts down all MCPServerStdio instances managed by the pool.
        This involves calling cleanup() on each server.
        """
        logger.info(f"Shutting down MCPServerStdioPool. Cleaning up {len(self.all_servers)} servers...")
        
        # Drain the queue to prevent new acquisitions during shutdown
        # and to get all servers that might be in the queue back into all_servers if not already.
        # However, all_servers should already have all instances ever created.
        while not self.available_servers.empty():
            try:
                server_in_queue = self.available_servers.get_nowait()
                if server_in_queue not in self.all_servers:
                    # This case should ideally not happen if all_servers is managed correctly
                    logger.warning(f"Server {server_in_queue.name} from queue was not in all_servers. Adding for cleanup.")
                    self.all_servers.append(server_in_queue) 
            except asyncio.QueueEmpty:
                break # Queue is empty

        for server in self.all_servers:
            try:
                logger.info(f"Cleaning up server (Name: {server.name})...")
                await server.cleanup()
                logger.info(f"Successfully cleaned up server (Name: {server.name}).")
            except Exception as e:
                logger.error(f"Error during cleanup of server (Name: {server.name}): {e}", exc_info=True)
                # Continue to try and clean up other servers
        
        self.all_servers.clear()
        # Re-initialize the queue to be empty
        self.available_servers = asyncio.Queue(maxsize=self.pool_size)
        logger.info("MCPServerStdioPool shutdown complete. All servers cleaned up and resources cleared.")

# Example Usage (optional, for testing purposes, would typically be removed or in a test file)
async def main():
    # This is a placeholder for how one might test the pool.
    # Ensure DINGTALK_APP_KEY and DINGTALK_APP_SECRET are set in environment or settings
    # for create_employee_info_mcp to work.
    
    # Mock settings if not available for basic testing
    from app.config.settings import settings as app_settings
    if not app_settings.DINGTALK_CLIENT_ID or not app_settings.DINGTALK_CLIENT_SECRET:
        logger.warning("Missing DINGTALK_CLIENT_ID or DINGTALK_CLIENT_SECRET for full test. MCP server might fail.")
        # You might want to mock create_employee_info_mcp if these are not available
        # For now, let it try and potentially fail if settings are missing.

    pool = MCPServerStdioPool(pool_size=2)
    try:
        await pool.initialize()
        logger.info(f"Pool initialized. Available servers: {pool.available_servers.qsize()}")

        if pool.available_servers.qsize() > 0:
            s1 = await pool.acquire()
            logger.info(f"Acquired s1: {s1.name}")
            
            s2 = await pool.acquire()
            logger.info(f"Acquired s2: {s2.name}")

            await pool.release(s1)
            logger.info(f"Released s1. Available: {pool.available_servers.qsize()}")
            
            await pool.release(s2)
            logger.info(f"Released s2. Available: {pool.available_servers.qsize()}")
            
            # Test acquiring again
            s3 = await pool.acquire()
            logger.info(f"Acquired s3: {s3.name}")
            await pool.release(s3)
            logger.info(f"Released s3. Available: {pool.available_servers.qsize()}")

    except Exception as e:
        logger.error(f"An error occurred during pool operations: {e}", exc_info=True)
    finally:
        await pool.shutdown()
        logger.info("Pool operations finished.")

if __name__ == "__main__":
    # Configure Loguru for better console output if running this file directly
    import sys
    logger.remove()
    logger.add(sys.stderr, level="DEBUG") # Show DEBUG level logs for testing
    
    # This part requires an event loop to run.
    # asyncio.run(main()) # Python 3.7+
    # For older versions or different environments:
    # loop = asyncio.get_event_loop()
    # try:
    #     loop.run_until_complete(main())
    # finally:
    #     loop.close()
    pass # Keep the example code, but don't run it as part of the tool execution.
