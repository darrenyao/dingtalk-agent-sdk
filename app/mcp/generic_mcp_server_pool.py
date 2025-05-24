import asyncio
from loguru import logger
from typing import Callable, Awaitable, List, Any
# Assuming 'agents.mcp.MCPServer' might not be a concrete base class
# or might not be available. Using Any for now for broader compatibility.
# If a specific MCPServer base class with a 'cleanup' method exists,
# it should be used instead of Any.
from agents.mcp import MCPServer # Assuming this is the base class or a relevant type.

class GenericMCPServerPool:
    def __init__(self, pool_name: str, pool_size: int, server_factory: Callable[[], Awaitable[MCPServer]]):
        """
        Initializes the Generic MCP Server Pool.

        Args:
            pool_name: Name of the pool, used for logging.
            pool_size: The maximum number of MCPServer instances to manage.
            server_factory: An async callable that returns a new MCPServer instance.
        """
        if pool_size <= 0:
            raise ValueError("Pool size must be positive.")
        if not callable(server_factory):
            raise TypeError("server_factory must be a callable.")

        self.pool_name: str = pool_name
        self.pool_size: int = pool_size
        self.server_factory: Callable[[], Awaitable[MCPServer]] = server_factory
        
        self.available_servers: asyncio.Queue[MCPServer] = asyncio.Queue(maxsize=self.pool_size)
        self.all_servers: List[MCPServer] = []
        
        logger.info(f"GenericMCPServerPool '{self.pool_name}' created with size {self.pool_size}.")

    async def initialize(self):
        """
        Creates and initializes the MCPServer instances for the pool using the server_factory.
        If any server fails to initialize, an exception is raised after cleaning up
        any servers already created during this initialization attempt.
        """
        logger.info(f"Initializing GenericMCPServerPool '{self.pool_name}' with {self.pool_size} servers...")
        servers_created_this_attempt: List[MCPServer] = []
        try:
            for i in range(self.pool_size):
                server_id_log = f"server {i + 1}/{self.pool_size}"
                logger.info(f"Pool '{self.pool_name}': Attempting to create {server_id_log} via factory...")
                
                mcp_server = await self.server_factory()
                # Assuming factory also handles connection or server is ready.
                # If server has a name attribute, it could be logged too.
                # e.g., logger.info(f"Pool '{self.pool_name}': Successfully created {server_id_log} (Name: {getattr(mcp_server, 'name', 'N/A')}).")

                servers_created_this_attempt.append(mcp_server)
                self.available_servers.put_nowait(mcp_server)
                # self.all_servers will be populated at the end of successful initialization
                # to simplify cleanup logic on partial failure.
                logger.info(f"Pool '{self.pool_name}': Successfully created and added {server_id_log} to available queue.")

            # Add all successfully created servers to all_servers list only after all are created
            self.all_servers.extend(servers_created_this_attempt)
            logger.info(f"GenericMCPServerPool '{self.pool_name}' initialization complete. {len(self.all_servers)} servers ready.")

        except Exception as e:
            logger.error(f"Pool '{self.pool_name}': Failed to initialize. Error during server factory call: {e}", exc_info=True)
            logger.warning(f"Pool '{self.pool_name}': Cleaning up {len(servers_created_this_attempt)} already created servers due to initialization failure.")
            for srv_to_clean in servers_created_this_attempt:
                try:
                    # Remove from available_servers if it was added (it was, via put_nowait)
                    # This requires getting it from the queue, which is tricky if other things are happening.
                    # Simpler: don't add to all_servers until the end. Clear available_servers.
                    await srv_to_clean.cleanup()
                    logger.info(f"Pool '{self.pool_name}': Cleaned up server during partial shutdown (Name: {getattr(srv_to_clean, 'name', 'N/A')}).")
                except Exception as cleanup_exc:
                    logger.error(f"Pool '{self.pool_name}': Error cleaning up server during partial shutdown (Name: {getattr(srv_to_clean, 'name', 'N/A')}): {cleanup_exc}", exc_info=True)
            
            # Empty the queue as its contents are now invalid or cleaned up
            while not self.available_servers.empty():
                try:
                    self.available_servers.get_nowait()
                except asyncio.QueueEmpty:
                    break
            # Ensure all_servers only contains successfully initialized and *not* cleaned-up servers.
            # Since we only add to all_servers on full success, it should be empty here.
            # If we added one-by-one, we'd need to remove them here.
            self.all_servers.clear() # Clears if any were added before a failure in a different logic.
            
            raise  # Re-raise the original exception that caused initialization to fail

    async def acquire(self) -> MCPServer:
        """
        Acquires an available MCPServer instance from the pool.
        Waits if no server is currently available.

        Returns:
            An MCPServer instance.
        """
        logger.debug(f"Pool '{self.pool_name}': Attempting to acquire an MCP server...")
        server = await self.available_servers.get()
        # server_name = getattr(server, 'name', 'N/A') # Example: get server name if available
        logger.info(f"Pool '{self.pool_name}': MCP server acquired. Queue size: {self.available_servers.qsize()}")
        return server

    async def release(self, server: MCPServer, is_healthy: bool = True):
        """
        Releases an MCPServer instance back to the pool or cleans it up if unhealthy.

        Args:
            server: The MCPServer instance to release.
            is_healthy: True if the server is considered healthy and can be reused,
                        False if it's unhealthy and should be cleaned up and removed.
        """
        # server_name = getattr(server, 'name', 'N/A')
        if server is None:
            logger.warning(f"Pool '{self.pool_name}': Attempted to release a None server. Ignoring.")
            return

        if is_healthy:
            logger.debug(f"Pool '{self.pool_name}': Attempting to release healthy MCP server back to the pool...")
            try:
                self.available_servers.put_nowait(server) # Use put_nowait as per design for QueueFull handling
                logger.info(f"Pool '{self.pool_name}': Healthy MCP server released back to the pool. Queue size: {self.available_servers.qsize()}")
            except asyncio.QueueFull:
                logger.error(f"Pool '{self.pool_name}': Failed to release healthy server. Pool queue is unexpectedly full. Cleaning up server.")
                try:
                    await server.cleanup()
                    logger.info(f"Pool '{self.pool_name}': Successfully cleaned up healthy server that couldn't be returned to full queue.")
                except Exception as e:
                    logger.error(f"Pool '{self.pool_name}': Error during direct cleanup of healthy server that couldn't be released to full queue: {e}", exc_info=True)
                finally:
                    if server in self.all_servers:
                        self.all_servers.remove(server)
                        logger.info(f"Pool '{self.pool_name}': Server removed from all_servers list after cleanup due to full queue. Current all_servers count: {len(self.all_servers)}")
        else:
            logger.warning(f"Pool '{self.pool_name}': Processing unhealthy MCP server. It will be cleaned up and removed from the pool.")
            try:
                await server.cleanup()
                logger.info(f"Pool '{self.pool_name}': Successfully cleaned up unhealthy server.")
            except Exception as e:
                logger.error(f"Pool '{self.pool_name}': Error during cleanup of unhealthy server: {e}", exc_info=True)
            finally:
                if server in self.all_servers:
                    self.all_servers.remove(server)
                    logger.info(f"Pool '{self.pool_name}': Unhealthy server removed from all_servers list. Current all_servers count: {len(self.all_servers)}")
                else:
                    logger.warning(f"Pool '{self.pool_name}': Unhealthy server was not found in all_servers list for removal. This might indicate a double release or prior removal.")
                # Note: No replenishment logic is part of this class's direct responsibility.

    async def shutdown(self):
        """
        Shuts down all MCPServer instances managed by the pool.
        This involves calling cleanup() on each server.
        """
        logger.info(f"Pool '{self.pool_name}': Shutting down. Cleaning up {len(self.all_servers)} servers...")
        
        # Create a copy for iteration, as self.all_servers might be modified if release is called unexpectedly
        servers_to_shutdown = list(self.all_servers)
        self.all_servers.clear() # Clear original list early

        # Also drain the queue to catch any servers that might be in flight / not in all_servers if logic was different
        # However, with current logic, all_servers should be the definitive list of active servers.
        while not self.available_servers.empty():
            try:
                server_in_queue = self.available_servers.get_nowait()
                if server_in_queue not in servers_to_shutdown: # Should not happen with current logic
                    servers_to_shutdown.append(server_in_queue)
                    logger.warning(f"Pool '{self.pool_name}': Server from queue was not in all_servers during shutdown. Added for cleanup.")
            except asyncio.QueueEmpty:
                break # Queue is empty

        for server in servers_to_shutdown:
            # server_name = getattr(server, 'name', 'N/A')
            try:
                logger.info(f"Pool '{self.pool_name}': Cleaning up server...")
                await server.cleanup()
                logger.info(f"Pool '{self.pool_name}': Successfully cleaned up server.")
            except Exception as e:
                logger.error(f"Pool '{self.pool_name}': Error during cleanup of server: {e}", exc_info=True)
                # Continue to try and clean up other servers
        
        # Re-initialize the queue to be empty and correctly sized.
        self.available_servers = asyncio.Queue(maxsize=self.pool_size)
        logger.info(f"Pool '{self.pool_name}': Shutdown complete. All tracked servers processed for cleanup. Resources cleared.")

# Example of how MCPServer might be defined if not available
# (This would typically be in agents.mcp or agents.mcp.base)
# from abc import ABC, abstractmethod
# class MCPServer(ABC):
#     @abstractmethod
#     async def cleanup(self):
#         pass
#     # name: Optional[str] = None # Optional attribute
```
