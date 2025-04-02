"""
Trellis 3D Generation API Client.

This module provides a client for the Trellis 3D Generation API.
"""

import json
from typing import Dict, List, Optional, Any
from urllib.parse import urljoin

# Import aiohttp for async HTTP requests
import aiohttp
import asyncio

from .models import Task, TaskStatus
from .exceptions import TrellisAPIError, TrellisRequestError


class TrellisClient:
    """Client for the Trellis 3D Generation API."""
    
    def __init__(self, base_url: str = "http://21.6.198.96:6006"):
        """
        Initialize the Trellis API client.
        
        Args:
            base_url: The base URL for the Trellis API server.
        """
        self.base_url = base_url
        self._session: Optional[aiohttp.ClientSession] = None
    
    async def _ensure_session(self) -> aiohttp.ClientSession:
        """Ensure that an aiohttp session exists."""
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session
    
    async def close(self) -> None:
        """Close the client session."""
        if self._session and not self._session.closed:
            await self._session.close()
            self._session = None

    async def __aenter__(self) -> 'TripoClient':
        """Enter the async context manager."""
        await self._ensure_session()
        return self
    
    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        """Exit the async context manager."""
        await self.close()
    
    def _url(self, path: str) -> str:
        """
        Construct a full URL from a path.
        
        Args:
            path: The path to append to the base URL.
            
        Returns:
            The full URL.
        """
        # Remove leading slash if present
        path = path.lstrip('/')
        
        # Construct the full URL
        return f"{self.BASE_URL}/{path}"
    
    
    async def _request(
        self, 
        method: str, 
        endpoint: str, 
        **kwargs
    ) -> Dict[str, Any]:
        """
        Make a request to the Trellis API.
        
        Args:
            method: The HTTP method to use.
            endpoint: The API endpoint to request.
            **kwargs: Additional arguments to pass to the request.
            
        Returns:
            The JSON response from the API.
            
        Raises:
            TrellisAPIError: If the API returns an error response.
            TrellisRequestError: If there is an error making the request.
        """
        session = await self._ensure_session()
        url = urljoin(self.base_url, endpoint)
        
        # Ensure POST requests use JSON format
        if method.upper() == "POST":
            # Convert data to json if it exists
            if "data" in kwargs:
                kwargs["json"] = kwargs.pop("data")
            # Make sure headers include content-type
            if "headers" not in kwargs:
                kwargs["headers"] = {}
            kwargs["headers"]["Content-Type"] = "application/json"
        
        try:
            async with session.request(method, url, **kwargs) as response:
                # Check if the response is JSON
                content_type = response.headers.get("Content-Type", "")
                if "application/json" in content_type:
                    data = await response.json()
                else:
                    text = await response.text()
                    try:
                        data = json.loads(text)
                    except json.JSONDecodeError:
                        data = {"text": text}
                
                if response.status >= 400:
                    error_message = data.get("error", f"HTTP {response.status}")
                    raise TrellisAPIError(error_message, status_code=response.status, response=data)
                
                return data
        except aiohttp.ClientError as e:
            raise TrellisRequestError(f"Request error: {str(e)}", original_error=e)
    
    async def get_task(self, request_id: str) -> Task:
        """
        Get a task by its request ID.
        
        Args:
            request_id: The ID of the task to get.
            
        Returns:
            The task.
        """
        data = await self._request("GET", f"/task/{request_id}")
        return Task.from_dict(data)
    
    async def get_my_requests(self) -> List[Task]:
        """
        Get all tasks for the current client.
        
        Returns:
            A list of tasks.
        """
        data = await self._request("GET", "/my_requests")
        return [Task.from_dict(task) for task in data.get("requests", [])]
    
    async def image_to_3d(
        self,
        image_base64: str,
        geometry_sample_steps: int = 12,
        geometry_cfg_strength: float = 7.5,
        texture_sample_steps: int = 12,
        texture_cfg_strength: float = 3.5,
    ) -> str:
        """
        Create a 3D model from text.
        
        Args:
            prompt: The text prompt describing the model to create.
            negative_prompt: Text describing what to avoid in the model.
            sample_steps: Number of sampling steps.
            cfg_strength: Classifier-free guidance strength.
            seed: Random seed for generation (-1 for random).
            
        Returns:
            The request ID of the created task.
        """
        form_data = {
            "image_name": "", 
            "image_data": image_base64,
            "ss_sample_steps": str(geometry_sample_steps),
            "ss_cfg_strength": str(geometry_cfg_strength),
            "slat_sample_steps": str(texture_sample_steps), 
            "slat_cfg_strength": str(texture_cfg_strength), 
        }
        
        data = await self._request(
            "POST", 
            "/image_to_3d",
            data=form_data
        )
        
        return data.get("request_id", "")

    async def text_to_3d(
        self,
        prompt: str,
        negative_prompt: str = "",
        geometry_sample_steps: int = 12,
        geometry_cfg_strength: float = 7.5,
        texture_sample_steps: int = 12,
        texture_cfg_strength: float = 3.5,
    ) -> str:
        """
        Create a 3D model from text.
        
        Args:
            prompt: The text prompt describing the model to create.
            negative_prompt: Text describing what to avoid in the model.
            sample_steps: Number of sampling steps.
            cfg_strength: Classifier-free guidance strength.
            seed: Random seed for generation (-1 for random).
            
        Returns:
            The request ID of the created task.
        """
        form_data = {
            "text": prompt,
            "negative_text": negative_prompt,
            "ss_sample_steps": str(geometry_sample_steps),
            "ss_cfg_strength": str(geometry_cfg_strength),
            "slat_sample_steps": str(texture_sample_steps), 
            "slat_cfg_strength": str(texture_cfg_strength), 
        }
        
        data = await self._request(
            "POST", 
            "/text_to_3d",
            data=form_data
        )
        
        return data.get("request_id", "")
    
   
    
    async def poll_task_status(
        self,
        request_id: str,
        interval: float = 5.0,
        max_attempts: int = 60
    ) -> Task:
        """
        Poll a task until it completes or fails.
        
        Args:
            request_id: The ID of the task to poll.
            interval: The interval between polls in seconds.
            max_attempts: The maximum number of polling attempts.
            
        Returns:
            The completed task.
            
        Raises:
            TimeoutError: If the task does not complete within the maximum number of attempts.
        """
        for _ in range(max_attempts):
            task = await self.get_task(request_id)
            
            if task.status in [TaskStatus.COMPLETE, TaskStatus.ERROR]:
                return task
            
            await asyncio.sleep(interval)
        
        raise TimeoutError(f"Task {request_id} did not complete within {max_attempts * interval} seconds")
