"""
Data models for the Trellis API client.
"""

from dataclasses import dataclass
from typing import Dict, List, Optional, Any, Union
from enum import Enum
import datetime


class TaskStatus(str, Enum):
    """Task status enum."""
    QUEUED = "QUEUED"
    PROCESSING = "PROCESSING"
    COMPLETE = "COMPLETE"
    ERROR = "ERROR"


@dataclass
class Task:
    """Task data model."""
    client_ip: str
    request_id: str
    task_type: str
    status: TaskStatus
    input_path: Optional[str] = None
    input_text: Optional[str] = None
    mesh_input_path: Optional[str] = None
    request_output_dir: Optional[str] = None
    is_dv_mode: bool = False
    image_name: Optional[str] = None
    start_time: Optional[datetime.datetime] = None
    finish_time: Optional[datetime.datetime] = None
    error: Optional[str] = None
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Task':
        """Create a Task from a dictionary."""
        status_str = data.get('status', 'ERROR').upper()
        try:
            status = TaskStatus(status_str)
        except ValueError:
            status = TaskStatus.ERROR
            
        # Parse datetime strings if they exist
        start_time = None
        if 'start_time' in data and data['start_time']:
            try:
                start_time = datetime.datetime.fromisoformat(data['start_time'])
            except (ValueError, TypeError):
                pass
                
        finish_time = None
        if 'finish_time' in data and data['finish_time']:
            try:
                finish_time = datetime.datetime.fromisoformat(data['finish_time'])
            except (ValueError, TypeError):
                pass
        
        return cls(
            client_ip=data.get('client_ip', ''),
            request_id=data.get('request_id', ''),
            task_type=data.get('task_type', ''),
            status=status,
            input_path=data.get('input_path'),
            input_text=data.get('input_text'),
            mesh_input_path=data.get('mesh_input_path'),
            request_output_dir=data.get('request_output_dir'),
            is_dv_mode=data.get('is_dv_mode', False),
            image_name=data.get('image_name'),
            start_time=start_time,
            finish_time=finish_time,
            error=data.get('error')
        )
