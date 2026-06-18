"""
report_dto.py — Pydantic models for reports data transfer.
"""

from pydantic import BaseModel
from typing import Any, List, Optional

class SaveReportRequest(BaseModel):
    session_id: Optional[str] = None
    title: str
    description: str = ""
    prompt: str = ""
    content: str
    report_type: str = "insight"
    chart_data: Optional[Any] = None
    table_data: Optional[List[dict]] = None
    kpis: Optional[List[dict]] = None
    metadata: Optional[dict] = None
    file_id: Optional[str] = None
    filename: Optional[str] = None
    tags: List[str] = []

class UpdateReportRequest(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    tags: Optional[List[str]] = None
    starred: Optional[bool] = None
    scheduled: Optional[bool] = None
    schedule_cron: Optional[str] = None

class CreateVersionRequest(BaseModel):
    content: str
    chart_data: Optional[Any] = None
    kpis: Optional[List[dict]] = None
    metadata: Optional[dict] = None
