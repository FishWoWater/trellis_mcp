import sys
import asyncio
from pathlib import Path
from typing import Dict, Any, List, AsyncIterator
import socket
import json
import logging
from dataclasses import dataclass 
from contextlib import asynccontextmanager
from mcp.server.fastmcp import FastMCP, Context

# Configure logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("TrellisMCPServer")

# Add the parent directory to the path to import the trellis_api module
sys.path.insert(0, str(Path(__file__).parent))
print(str(Path(__file__).parent))

from trellis_api import TrellisClient, TaskStatus

# Global connection to Blender
_blender_connection = None
_blender_lock = asyncio.Lock()

# Global Trellis client
_trellis_client = None



@dataclass
class BlenderConnection:
    host: str
    port: int
    sock: socket.socket = (
        None  # Changed from 'socket' to 'sock' to avoid naming conflict
    )

    def connect(self) -> bool:
        """Connect to the Blender addon socket server"""
        if self.sock:
            return True

        try:
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.sock.connect((self.host, self.port))
            logger.info(f"Connected to Blender at {self.host}:{self.port}")
            return True
        except Exception as e:
            logger.error(f"Failed to connect to Blender: {str(e)}")
            self.sock = None
            return False

    def disconnect(self):
        """Disconnect from the Blender addon"""
        if self.sock:
            try:
                self.sock.close()
            except Exception as e:
                logger.error(f"Error disconnecting from Blender: {str(e)}")
            finally:
                self.sock = None

    def receive_full_response(self, sock, buffer_size=8192):
        """Receive the complete response, potentially in multiple chunks"""
        chunks = []
        # Use a consistent timeout value that matches the addon's timeout
        sock.settimeout(15.0)  # Match the addon's timeout

        try:
            while True:
                try:
                    chunk = sock.recv(buffer_size)
                    if not chunk:
                        # If we get an empty chunk, the connection might be closed
                        if (
                            not chunks
                        ):  # If we haven't received anything yet, this is an error
                            raise Exception(
                                "Connection closed before receiving any data"
                            )
                        break

                    chunks.append(chunk)

                    # Check if we've received a complete JSON object
                    try:
                        data = b"".join(chunks)
                        json.loads(data.decode("utf-8"))
                        # If we get here, it parsed successfully
                        logger.info(f"Received complete response ({len(data)} bytes)")
                        return data
                    except json.JSONDecodeError:
                        # Incomplete JSON, continue receiving
                        continue
                except socket.timeout:
                    # If we hit a timeout during receiving, break the loop and try to use what we have
                    logger.warning("Socket timeout during chunked receive")
                    break
                except (ConnectionError, BrokenPipeError, ConnectionResetError) as e:
                    logger.error(f"Socket connection error during receive: {str(e)}")
                    raise  # Re-raise to be handled by the caller
        except socket.timeout:
            logger.warning("Socket timeout during chunked receive")
        except Exception as e:
            logger.error(f"Error during receive: {str(e)}")
            raise

        # If we get here, we either timed out or broke out of the loop
        # Try to use what we have
        if chunks:
            data = b"".join(chunks)
            logger.info(f"Returning data after receive completion ({len(data)} bytes)")
            try:
                # Try to parse what we have
                json.loads(data.decode("utf-8"))
                return data
            except json.JSONDecodeError:
                # If we can't parse it, it's incomplete
                raise Exception("Incomplete JSON response received")
        else:
            raise Exception("No data received")

    def send_command(
        self, command_type: str, params: Dict[str, Any] = None
    ) -> Dict[str, Any]:
        """Send a command to Blender and return the response"""
        if not self.sock and not self.connect():
            raise ConnectionError("Not connected to Blender")

        command = {"type": command_type, "params": params or {}}

        try:
            # Log the command being sent
            logger.info(f"Sending command: {command_type} with params: {params}")

            # Send the command
            self.sock.sendall(json.dumps(command).encode("utf-8"))
            logger.info("Command sent, waiting for response...")

            # Set a timeout for receiving - use the same timeout as in receive_full_response
            self.sock.settimeout(15.0)  # Match the addon's timeout

            # Receive the response using the improved receive_full_response method
            response_data = self.receive_full_response(self.sock)
            logger.info(f"Received {len(response_data)} bytes of data")

            response = json.loads(response_data.decode("utf-8"))
            logger.info(f"Response parsed, status: {response.get('status', 'unknown')}")

            if response.get("status") == "error":
                logger.error(f"Blender error: {response.get('message')}")
                raise Exception(response.get("message", "Unknown error from Blender"))

            return response.get("result", {})
        except socket.timeout:
            logger.error("Socket timeout while waiting for response from Blender")
            # Don't try to reconnect here - let the get_blender_connection handle reconnection
            # Just invalidate the current socket so it will be recreated next time
            self.sock = None
            raise Exception(
                "Timeout waiting for Blender response - try simplifying your request"
            )
        except (ConnectionError, BrokenPipeError, ConnectionResetError) as e:
            logger.error(f"Socket connection error: {str(e)}")
            self.sock = None
            raise Exception(f"Connection to Blender lost: {str(e)}")
        except json.JSONDecodeError as e:
            logger.error(f"Invalid JSON response from Blender: {str(e)}")
            # Try to log what was received
            if "response_data" in locals() and response_data:
                logger.error(f"Raw response (first 200 bytes): {response_data[:200]}")
            raise Exception(f"Invalid response from Blender: {str(e)}")
        except Exception as e:
            logger.error(f"Error communicating with Blender: {str(e)}")
            # Don't try to reconnect here - let the get_blender_connection handle reconnection
            self.sock = None
            raise Exception(f"Communication error with Blender: {str(e)}")


@asynccontextmanager
async def server_lifespan(server: FastMCP) -> AsyncIterator[Dict[str, Any]]:
    """Manage server startup and shutdown lifecycle"""
    # We don't need to create a connection here since we're using the global connection
    # for resources and tools

    try:
        # Just log that we're starting up
        logger.info("Blender server starting up")

        # Try to connect to Blender on startup to verify it's available
        try:
            # This will initialize the global connection if needed
            blender = get_blender_connection()
            logger.info("Successfully connected to Blender on startup")
        except Exception as e:
            logger.warning(f"Could not connect to Blender on startup: {str(e)}")
            logger.warning(
                "Make sure the Blender addon is running before using Blender resources or tools"
            )

        # Return an empty context - we're using the global connection
        yield {}
    finally:
        # Clean up the global connection on shutdown
        global _blender_connection
        if _blender_connection:
            logger.info("Disconnecting from Blender on shutdown")
            _blender_connection.disconnect()
            _blender_connection = None
        logger.info("BlenderMCP server shut down")


# Create the MCP server
mcp = FastMCP(
    name="Trellis Blender MCP",
    instructions="Blender and Trellis(Text-to-3D) integration through the Model Context Protocol",
    lifespan=server_lifespan,
)

_blender_connection = None
_polyhaven_enabled = False  # Add this global variable

def get_blender_connection():
    """Get or create a persistent Blender connection"""
    global _blender_connection, _polyhaven_enabled  # Add _polyhaven_enabled to globals

    # If we have an existing connection, check if it's still valid
    if _blender_connection is not None:
        try:
            # First check if PolyHaven is enabled by sending a ping command
            result = _blender_connection.send_command("get_polyhaven_status")
            # Store the PolyHaven status globally
            _polyhaven_enabled = result.get("enabled", False)

            return _blender_connection
        except Exception as e:
            # Connection is dead, close it and create a new one
            logger.warning(f"Existing connection is no longer valid: {str(e)}")
            try:
                _blender_connection.disconnect()
            except:
                pass
            _blender_connection = None

    # Create a new connection if needed
    if _blender_connection is None:
        _blender_connection = BlenderConnection(host="localhost", port=9876)
        if not _blender_connection.connect():
            logger.error("Failed to connect to Blender")
            _blender_connection = None
            raise Exception(
                "Could not connect to Blender. Make sure the Blender addon is running."
            )
        logger.info("Created new persistent connection to Blender")

    return _blender_connection


@mcp.tool("get_scene_info")
async def get_scene_info(ctx: Context) -> Dict[str, Any]:
    """
    Get detailed information about the current Blender scene.
    
    Returns information about the scene, including objects, materials, and other properties.
    """
    try:
        blender = get_blender_connection()
        result = blender.send_command("get_scene_info")

        # Just return the JSON representation of what Blender sent us
        return json.dumps(result, indent=2)
    except Exception as e:
        logger.error(f"Error getting scene info: {e}")
        return {"error": str(e)}


@mcp.tool("get_object_info")
async def get_object_info(ctx: Context, object_name: str) -> Dict[str, Any]:
    """
    Get detailed information about a specific object in the Blender scene.
    
    Parameters:
    - object_name: The name of the object to get information about
    """
    try:
        blender = get_blender_connection()
        result = blender.send_command("get_object_info", {"name": object_name})

        # Just return the JSON representation of what Blender sent us
        return json.dumps(result, indent=2)
    except Exception as e:
        logger.error(f"Error getting object info: {e}")
        return {"error": str(e)}


@mcp.tool("create_object")
async def create_object(
    ctx: Context,
    type: str = "CUBE",
    name: str = None,
    location: List[float] = None,
    rotation: List[float] = None,
    scale: List[float] = None,
) -> Dict[str, Any]:
    """
    Create a new object in the Blender scene.
    
    Parameters:
    - type: Object type (CUBE, SPHERE, CYLINDER, PLANE, CONE, TORUS, EMPTY, CAMERA, LIGHT)
    - name: Optional name for the object
    - location: Optional [x, y, z] location coordinates
    - rotation: Optional [x, y, z] rotation in radians
    - scale: Optional [x, y, z] scale factors
    """
    try:
        # Get the global connection
        blender = get_blender_connection()

        # Set default values for missing parameters
        loc = location or [0, 0, 0]
        rot = rotation or [0, 0, 0]
        sc = scale or [1, 1, 1]

        params = {"type": type, "location": loc, "rotation": rot, "scale": sc}

        if name:
            params["name"] = name

        result = blender.send_command("create_object", params)
        return f"Created {type} object: {result['name']}"
    except Exception as e:
        logger.error(f"Error creating object: {e}")
        return {"error": str(e)}


@mcp.tool("modify_object")
async def modify_object(
    ctx: Context,
    name: str,
    location: List[float] = None,
    rotation: List[float] = None,
    scale: List[float] = None,
    visible: bool = None,
) -> Dict[str, Any]:
    """
    Modify an existing object in the Blender scene.
    
    Parameters:
    - name: Name of the object to modify
    - location: Optional [x, y, z] location coordinates
    - rotation: Optional [x, y, z] rotation in radians
    - scale: Optional [x, y, z] scale factors
    - visible: Optional boolean to set visibility
    """
    try:
        # Get the global connection
        blender = get_blender_connection()

        params = {"name": name}

        if location is not None:
            params["location"] = location
        if rotation is not None:
            params["rotation"] = rotation
        if scale is not None:
            params["scale"] = scale
        if visible is not None:
            params["visible"] = visible

        result = blender.send_command("modify_object", params)
        return f"Modified object: {result['name']}"
    except Exception as e:
        logger.error(f"Error modifying object: {e}")
        return {"error": str(e)}


@mcp.tool("delete_object")
async def delete_object(ctx: Context, name: str) -> Dict[str, Any]:
    """
    Delete an object from the Blender scene.
    
    Parameters:
    - name: Name of the object to delete
    """
    try:
        # Get the global connection
        blender = get_blender_connection()

        result = blender.send_command("delete_object", {"name": name})
        return f"Deleted object: {name}"
    except Exception as e:
        logger.error(f"Error deleting object: {e}")
        return {"error": str(e)}


@mcp.tool()
def set_material(
    ctx: Context, object_name: str, material_name: str = None, color: List[float] = None
) -> str:
    """
    Set or create a material for an object.

    Parameters:
    - object_name: Name of the object to apply the material to
    - material_name: Optional name of the material to use or create
    - color: Optional [R, G, B] color values (0.0-1.0)
    """
    try:
        # Get the global connection
        blender = get_blender_connection()

        params = {"object_name": object_name}

        if material_name:
            params["material_name"] = material_name
        if color:
            params["color"] = color

        result = blender.send_command("set_material", params)
        return f"Applied material to {object_name}: {result.get('material_name', 'unknown')}"
    except Exception as e:
        logger.error(f"Error setting material: {str(e)}")
        return f"Error setting material: {str(e)}"


@mcp.tool()
def execute_blender_code(ctx: Context, code: str) -> str:
    """
    Execute arbitrary Python code in Blender.

    Parameters:
    - code: The Python code to execute
    """
    try:
        # Get the global connection
        blender = get_blender_connection()

        result = blender.send_command("execute_code", {"code": code})
        return f"Code executed successfully: {result.get('result', '')}"
    except Exception as e:
        logger.error(f"Error executing code: {str(e)}")
        return f"Error executing code: {str(e)}"

@mcp.tool()
def get_polyhaven_categories(ctx: Context, asset_type: str = "hdris") -> str:
    """
    Get a list of categories for a specific asset type on Polyhaven.

    Parameters:
    - asset_type: The type of asset to get categories for (hdris, textures, models, all)
    """
    try:
        blender = get_blender_connection()
        if not _polyhaven_enabled:
            return "PolyHaven integration is disabled. Select it in the sidebar in BlenderMCP, then run it again."
        result = blender.send_command(
            "get_polyhaven_categories", {"asset_type": asset_type}
        )

        if "error" in result:
            return f"Error: {result['error']}"

        # Format the categories in a more readable way
        categories = result["categories"]
        formatted_output = f"Categories for {asset_type}:\n\n"

        # Sort categories by count (descending)
        sorted_categories = sorted(categories.items(), key=lambda x: x[1], reverse=True)

        for category, count in sorted_categories:
            formatted_output += f"- {category}: {count} assets\n"

        return formatted_output
    except Exception as e:
        logger.error(f"Error getting Polyhaven categories: {str(e)}")
        return f"Error getting Polyhaven categories: {str(e)}"


@mcp.tool()
def search_polyhaven_assets(
    ctx: Context, asset_type: str = "all", categories: str = None
) -> str:
    """
    Search for assets on Polyhaven with optional filtering.

    Parameters:
    - asset_type: Type of assets to search for (hdris, textures, models, all)
    - categories: Optional comma-separated list of categories to filter by

    Returns a list of matching assets with basic information.
    """
    try:
        blender = get_blender_connection()
        result = blender.send_command(
            "search_polyhaven_assets",
            {"asset_type": asset_type, "categories": categories},
        )

        if "error" in result:
            return f"Error: {result['error']}"

        # Format the assets in a more readable way
        assets = result["assets"]
        total_count = result["total_count"]
        returned_count = result["returned_count"]

        formatted_output = f"Found {total_count} assets"
        if categories:
            formatted_output += f" in categories: {categories}"
        formatted_output += f"\nShowing {returned_count} assets:\n\n"

        # Sort assets by download count (popularity)
        sorted_assets = sorted(
            assets.items(), key=lambda x: x[1].get("download_count", 0), reverse=True
        )

        for asset_id, asset_data in sorted_assets:
            formatted_output += (
                f"- {asset_data.get('name', asset_id)} (ID: {asset_id})\n"
            )
            formatted_output += (
                f"  Type: {['HDRI', 'Texture', 'Model'][asset_data.get('type', 0)]}\n"
            )
            formatted_output += (
                f"  Categories: {', '.join(asset_data.get('categories', []))}\n"
            )
            formatted_output += (
                f"  Downloads: {asset_data.get('download_count', 'Unknown')}\n\n"
            )

        return formatted_output
    except Exception as e:
        logger.error(f"Error searching Polyhaven assets: {str(e)}")
        return f"Error searching Polyhaven assets: {str(e)}"


@mcp.tool()
def download_polyhaven_asset(
    ctx: Context,
    asset_id: str,
    asset_type: str,
    resolution: str = "1k",
    file_format: str = None,
) -> str:
    """
    Download and import a Polyhaven asset into Blender.

    Parameters:
    - asset_id: The ID of the asset to download
    - asset_type: The type of asset (hdris, textures, models)
    - resolution: The resolution to download (e.g., 1k, 2k, 4k)
    - file_format: Optional file format (e.g., hdr, exr for HDRIs; jpg, png for textures; gltf, fbx for models)

    Returns a message indicating success or failure.
    """
    try:
        blender = get_blender_connection()
        result = blender.send_command(
            "download_polyhaven_asset",
            {
                "asset_id": asset_id,
                "asset_type": asset_type,
                "resolution": resolution,
                "file_format": file_format,
            },
        )

        if "error" in result:
            return f"Error: {result['error']}"

        if result.get("success"):
            message = result.get(
                "message", "Asset downloaded and imported successfully"
            )

            # Add additional information based on asset type
            if asset_type == "hdris":
                return f"{message}. The HDRI has been set as the world environment."
            elif asset_type == "textures":
                material_name = result.get("material", "")
                maps = ", ".join(result.get("maps", []))
                return (
                    f"{message}. Created material '{material_name}' with maps: {maps}."
                )
            elif asset_type == "models":
                return f"{message}. The model has been imported into the current scene."
            else:
                return message
        else:
            return f"Failed to download asset: {result.get('message', 'Unknown error')}"
    except Exception as e:
        logger.error(f"Error downloading Polyhaven asset: {str(e)}")
        return f"Error downloading Polyhaven asset: {str(e)}"


@mcp.tool()
def set_texture(ctx: Context, object_name: str, texture_id: str) -> str:
    """
    Apply a previously downloaded Polyhaven texture to an object.

    Parameters:
    - object_name: Name of the object to apply the texture to
    - texture_id: ID of the Polyhaven texture to apply (must be downloaded first)

    Returns a message indicating success or failure.
    """
    try:
        # Get the global connection
        blender = get_blender_connection()

        result = blender.send_command(
            "set_texture", {"object_name": object_name, "texture_id": texture_id}
        )

        if "error" in result:
            return f"Error: {result['error']}"

        if result.get("success"):
            material_name = result.get("material", "")
            maps = ", ".join(result.get("maps", []))

            # Add detailed material info
            material_info = result.get("material_info", {})
            node_count = material_info.get("node_count", 0)
            has_nodes = material_info.get("has_nodes", False)
            texture_nodes = material_info.get("texture_nodes", [])

            output = f"Successfully applied texture '{texture_id}' to {object_name}.\n"
            output += f"Using material '{material_name}' with maps: {maps}.\n\n"
            output += f"Material has nodes: {has_nodes}\n"
            output += f"Total node count: {node_count}\n\n"

            if texture_nodes:
                output += "Texture nodes:\n"
                for node in texture_nodes:
                    output += f"- {node['name']} using image: {node['image']}\n"
                    if node["connections"]:
                        output += "  Connections:\n"
                        for conn in node["connections"]:
                            output += f"    {conn}\n"
            else:
                output += "No texture nodes found in the material.\n"

            return output
        else:
            return f"Failed to apply texture: {result.get('message', 'Unknown error')}"
    except Exception as e:
        logger.error(f"Error applying texture: {str(e)}")
        return f"Error applying texture: {str(e)}"


@mcp.tool()
def get_polyhaven_status(ctx: Context) -> str:
    """
    Check if PolyHaven integration is enabled in Blender.
    Returns a message indicating whether PolyHaven features are available.
    """
    try:
        blender = get_blender_connection()
        result = blender.send_command("get_polyhaven_status")
        enabled = result.get("enabled", False)
        message = result.get("message", "")

        return message
    except Exception as e:
        logger.error(f"Error checking PolyHaven status: {str(e)}")
        return f"Error checking PolyHaven status: {str(e)}"


@mcp.tool("create_3d_model_from_text_trellis")
async def create_3d_model_from_text_trellis(
    ctx: Context,
    prompt: str,
    negative_prompt: str = "",
    geometry_sample_steps: int = 12,
    geometry_cfg_strength: float = 7.5,
    texture_sample_steps: int = 12, 
    texture_cfg_strength: float = 3.5,

) -> Dict[str, Any]:
    """
    Create a 3D model from a text description using the Trellis API.
    
    IMPORTANT: This tool initiates a 3D model generation task but does NOT wait for completion.
    After calling this tool, you MUST repeatedly call the get_trellis_task_status tool with the returned
    task_id until the task status is COMPLETE or ERROR.
    
    Parameters:
    - prompt: A detailed description of the object to generate
    - negative_prompt: Optional text describing what to avoid in the model
    - geometry_sample_steps: Number of sampling steps for the geometry generation (default: 12)
    - geometry_cfg_strength: Classifier-free guidance strength for the geometry generation (default: 7.5)
    - texture_sample_steps: Number of sampling steps for the texture generation (default: 12)
    - texture_cfg_strength: Classifier-free guidance strength for the texture generation (default: 3.5)
    
    Returns:
    A dictionary containing the task ID and instructions for checking the status.
    """
    try:
        async with TrellisClient() as client:
            # Start the text-to-3D task
            task_id = await client.text_to_3d(
                prompt=prompt,
                negative_prompt=negative_prompt,
                geometry_sample_steps=geometry_sample_steps,
                geometry_cfg_strength=geometry_cfg_strength,
                texture_sample_steps=texture_sample_steps,
                texture_cfg_strength=texture_cfg_strength
            )
            
            if not task_id:
                return {
                    "error": "Failed to start text-to-3D task. No task ID returned."
                }
            
            return {
                "task_id": task_id,
                "status": "queued", 
                "message": "Task created successfully. The 3D model generation is in progress.",
                "next_step": "You MUST now call get_trellis_task_status with this task_id to check progress.",
                "important_note": "3D model generation takes tens of seconds. You need to repeatedly call get_trellis_task_status until completion.",
                "workflow": [
                    "1. You've completed this step by calling create_3d_model_from_text_trellis",
                    "2. Now call get_trellis_task_status with task_id: " + task_id,
                    "3. If status is not COMPLETE, wait and call get_trellis_task_status again",
                    "4. When status is COMPLETE, use the model_url from the response",
                ],
            }

    except Exception as e:
        logger.error(f"Error creating 3D model from text: {e}")
        return {"error": str(e)}

@mcp.tool("get_trellis_task_status")
async def get_trellis_task_status(task_id: str) -> Dict[str, Any]:
    """
    Get the status of a 3D model generation task.

    IMPORTANT: This tool checks the status of a task started by create_3d_model_from_text_trellis.
    You may need to call this tool MULTIPLE TIMES until the task completes.

    Typical workflow:
    1. Call this tool with the task_id from create_3d_model_from_text_trellis
    2. Check the status in the response:
       - If status is complete, the task is complete and you can use the model_url
       - If status is error, the task failed
       - If status is anything else (processing, queued), the task is still in progress
    3. If the task is still in progress, wait a moment and call this tool again

    Args:
        task_id: The ID of the task to check (obtained from create_3d_model_from_text_trellis).

    Returns:
        A dictionary containing the task status and other information.
    """
    try:
        async with TrellisClient() as client:
            # Try up to 5 times if the status is queued
            retry_count = 0
            max_retries = 5
            task = await client.get_task(task_id)

            # here it's important to reduce the number of llm credits 
            while (task.status.value == "queued" or task.status.value == "processing") and retry_count < max_retries:
                # Wait for 1 second before retrying
                await asyncio.sleep(1)
                retry_count += 1
                logger.info(f"Task {task_id} still queued, retrying ({retry_count}/{max_retries})")
                task = await client.get_task(task_id)
            
            result = {
                "task_id": task.request_id,
                "status": task.status.value,
                "task_type": task.task_type,
            }
            
            # Add additional information based on task status
            if task.status == TaskStatus.COMPLETE:
                # For completed tasks, add URLs to the output files
                base_url = client.base_url
                output_dir = task.request_output_dir
                
                if output_dir:
                    # The output directory is relative to the server
                    # We need to construct URLs to the output files
                    file_url = f"{base_url}/output/{task.client_ip}/{task.request_id}/output.glb"
                    result.update({
                        "model_url": file_url, 
                        "message": "Task completed successfully. You can now use the model_url.", 
                        "next_step": "Use the model_url to access the 3D model, download it through import_trellis_glb_model tool"
                    })
                else:
                    result["message"] = "Task completed but no output directory was found."
            
            elif task.status == TaskStatus.ERROR:
                # For failed tasks, add the error message
                result["error"] = task.error or "Unknown error"
                result["message"] = f"Task failed: {task.error}"
    
            else:
                # For pending tasks, add a message to check again later
                result["message"] = (
                    f"Task is still in progress. Current status: {task.status.value}"
                )
                result["next_step"] = (
                    "IMPORTANT: You must call get_trellis_task_status again with this task_id to continue checking progress."
                )
            
            return result
    except Exception as e:
        logger.error(f"Error getting task status: {e}")
        return {"error": str(e)}


@mcp.tool("import_trellis_glb_model")
async def import_trellis_glb_model(ctx: Context, model_url: str) -> Dict[str, Any]:
    """
    Import a 3D model from a URL into the Blender scene.
    
    Parameters:
    - model_url: The URL of the model to import
    
    Returns:
    A dictionary containing information about the imported model.
    """
    try:
        blender = get_blender_connection()
        result = blender.send_command("import_trellis_glb_model", {"url": model_url})

        if "error" in result:
            return f"Import failed: {result['error']}"

        if result.get("status") == "success":
            output = ["Successfully imported models:"]
            for model in result.get("models", []):
                dim = model["dimensions"]
                output.append(
                    f"• {model['name']} | Dimensions: "
                    f"{dim['x']} x {dim['y']} x {dim['z']} meters"
                )

            if not output:
                output.append("No models found in imported file")

            return "\n".join(output)
        else:
            return f"Import failed: {result.get('message', 'Unknown error')}"

    except Exception as e:
        logger.error(f"Error importing model: {e}")
        return {"error": str(e)}


@mcp.prompt()
def asset_creation_strategy() -> str:
    """Defines the preferred strategy for creating assets in Blender"""
    return """When creating 3D content in Blender, always start by checking if integrations are available:

    0. Before anything, always check the scene from get_scene_info()
    1. First use the following tools to verify if the following integrations are enabled:
        1. PolyHaven
            Use get_polyhaven_status() to verify its status
            If PolyHaven is enabled:
            - For objects/models: Use download_polyhaven_asset() with asset_type="models"
            - For materials/textures: Use download_polyhaven_asset() with asset_type="textures"
            - For environment lighting: Use download_polyhaven_asset() with asset_type="hdris"
        2. Trellis
            Trellis is good at generating 3D models for single item.
            So don't try to:
            1. Generate the whole scene with one shot
            2. Generate ground using Trellis
            3. Generate parts of the items separately and put them together afterwards

            Use get_trellis_task_status() to verify its status
            
            - When using trellis to create 3D models/objects, do the following steps:
                1. Create the model generation task
                    - Use create_3d_model_from_text_trellis() if generating 3D asset using text prompt
                2. Poll the status
                    - Use get_trellis_task_status() to check if the generation task has completed or failed
                3. Import the asset
                    - Use import_trellis_glb_model() to import the generated GLB model the asset
                4. After importing the asset, ALWAYS check the world_bounding_box of the imported mesh, and adjust the mesh's location and size
                    Adjust the imported mesh's location, scale, rotation, so that the mesh is on the right spot.

                You can reuse assets previous generated by running python code to duplicate the object, without creating another generation task.

    2. If all integrations are disabled or when falling back to basic tools:
       - create_object() for basic primitives (CUBE, SPHERE, CYLINDER, etc.)
       - set_material() for basic colors and materials
    
    3. When including an object into scene, ALWAYS make sure that the name of the object is meanful.

    4. Always check the world_bounding_box for each item so that:
        - Ensure that all objects that should not be clipping are not clipping.
        - Items have right spatial relationship.
    
    5. After giving the tool location/scale/rotation information (via create_object() and modify_object()),
       double check the related object's location, scale, rotation, and world_bounding_box using get_object_info(),
       so that the object is in the desired location.

    Only fall back to basic creation tools when:
    - PolyHaven and Trellis are disabled
    - A simple primitive is explicitly requested
    - No suitable PolyHaven asset exists
    - Trellis failed to generate the desired asset
    - The task specifically requires a basic material/color
    """


def main():
    """Run the MCP server."""
    # Set the host and port from environment variables or use defaults
    mcp.run()


if __name__ == "__main__":
    main()
