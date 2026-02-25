"""Asana API client."""
import httpx
from typing import Optional, List, Dict, Any
from .auth import get_valid_token

BASE_URL = "https://app.asana.com/api/1.0"


class AsanaClient:
    """Async client for Asana API."""
    
    def __init__(self, access_token: Optional[str] = None):
        self._token = access_token
        self._client: Optional[httpx.AsyncClient] = None
    
    async def __aenter__(self):
        if not self._token:
            self._token = await get_valid_token()
        if not self._token:
            raise ValueError("No valid Asana token. Run authorization flow first.")
        
        self._client = httpx.AsyncClient(
            base_url=BASE_URL,
            headers={
                "Authorization": f"Bearer {self._token}",
                "Accept": "application/json",
            },
            timeout=30.0,
        )
        return self
    
    async def __aexit__(self, *args):
        if self._client:
            await self._client.aclose()
    
    async def _get(self, path: str, **params) -> Dict[str, Any]:
        """GET request to Asana API."""
        response = await self._client.get(path, params=params)
        response.raise_for_status()
        return response.json()
    
    async def _post(self, path: str, data: Dict[str, Any]) -> Dict[str, Any]:
        """POST request to Asana API."""
        response = await self._client.post(path, json={"data": data})
        response.raise_for_status()
        return response.json()
    
    async def _put(self, path: str, data: Dict[str, Any]) -> Dict[str, Any]:
        """PUT request to Asana API."""
        response = await self._client.put(path, json={"data": data})
        response.raise_for_status()
        return response.json()
    
    # User/workspace methods
    async def me(self) -> Dict[str, Any]:
        """Get current user info."""
        return await self._get("/users/me")
    
    async def workspaces(self) -> List[Dict[str, Any]]:
        """List workspaces."""
        result = await self._get("/workspaces")
        return result.get("data", [])
    
    # Project methods
    async def projects(self, workspace_gid: str) -> List[Dict[str, Any]]:
        """List projects in a workspace."""
        result = await self._get("/projects", workspace=workspace_gid)
        return result.get("data", [])
    
    async def project(self, project_gid: str) -> Dict[str, Any]:
        """Get project details."""
        return await self._get(f"/projects/{project_gid}")
    
    async def project_sections(self, project_gid: str) -> List[Dict[str, Any]]:
        """Get sections in a project."""
        result = await self._get(f"/projects/{project_gid}/sections")
        return result.get("data", [])
    
    # Task methods
    async def tasks(
        self, 
        project_gid: Optional[str] = None,
        section_gid: Optional[str] = None,
        assignee: Optional[str] = None,
        workspace_gid: Optional[str] = None,
        completed_since: Optional[str] = None,
        opt_fields: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        """List tasks with filters."""
        params = {}
        if project_gid:
            params["project"] = project_gid
        if section_gid:
            params["section"] = section_gid
        if assignee:
            params["assignee"] = assignee
        if workspace_gid:
            params["workspace"] = workspace_gid
        if completed_since:
            params["completed_since"] = completed_since
        if opt_fields:
            params["opt_fields"] = ",".join(opt_fields)
        
        result = await self._get("/tasks", **params)
        return result.get("data", [])
    
    async def task(self, task_gid: str, opt_fields: Optional[List[str]] = None) -> Dict[str, Any]:
        """Get task details."""
        params = {}
        if opt_fields:
            params["opt_fields"] = ",".join(opt_fields)
        return await self._get(f"/tasks/{task_gid}", **params)
    
    async def create_task(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Create a new task."""
        return await self._post("/tasks", data)
    
    async def update_task(self, task_gid: str, data: Dict[str, Any]) -> Dict[str, Any]:
        """Update a task."""
        return await self._put(f"/tasks/{task_gid}", data)
    
    # Search
    async def search_tasks(
        self, 
        workspace_gid: str,
        text: Optional[str] = None,
        assignee: Optional[str] = None,
        projects: Optional[List[str]] = None,
        completed: Optional[bool] = None,
    ) -> List[Dict[str, Any]]:
        """Search tasks in workspace."""
        params = {"workspace": workspace_gid}
        if text:
            params["text"] = text
        if assignee:
            params["assignee.any"] = assignee
        if projects:
            params["projects.any"] = ",".join(projects)
        if completed is not None:
            params["completed"] = str(completed).lower()
        
        result = await self._get("/workspaces/{workspace_gid}/tasks/search", **params)
        return result.get("data", [])
