from fastapi import FastAPI, Depends, HTTPException, Request, status
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from typing import List, Optional
from datetime import datetime
from google.cloud import firestore
from google.oauth2 import service_account
import json
import requests

app = FastAPI(title="Task Management System")
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

# Load service account credentials
with open("service-account.json", "r") as f:
    service_account_info = json.load(f)

credentials = service_account.Credentials.from_service_account_info(
    service_account_info,
    scopes=["https://www.googleapis.com/auth/cloud-platform"]
)
db = firestore.Client(project="task-management-f337f", credentials=credentials)

# Models
class TaskBoardCreate(BaseModel):
    name: str

class TaskCreate(BaseModel):
    title: str
    due_date: str  # ISO format: "YYYY-MM-DD"
    assigned_users: Optional[List[str]] = []

class TaskUpdate(BaseModel):
    title: Optional[str]
    due_date: Optional[str]
    completed: Optional[bool]
    assigned_users: Optional[List[str]]

class UserAdd(BaseModel):
    email: str

# Token verification
async def get_current_user(request: Request):
    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    if not token:
        token = request.query_params.get("token", "")
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="No token provided")
    try:
        url = f"https://identitytoolkit.googleapis.com/v1/accounts:lookup?key=AIzaSyCpLrfjk5sRtYhJK7HsYzlEfnqoPKyK5MQ"
        response = requests.post(url, json={"idToken": token})
        if response.status_code != 200:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
        data = response.json()
        return data["users"][0]["localId"], token  # Return token along with user ID
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(e))

# Routes
@app.get("/", response_class=HTMLResponse)
async def root(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

@app.post("/taskboards/", response_model=dict)
async def create_task_board(board: TaskBoardCreate, user_data: tuple = Depends(get_current_user)):
    current_user, _ = user_data
    board_ref = db.collection("taskboards").document()
    board_data = {
        "name": board.name,
        "creator": current_user,
        "users": [current_user],
        "created_at": datetime.now().isoformat()
    }
    board_ref.set(board_data)
    return {"id": board_ref.id, **board_data}

@app.get("/taskboards/", response_model=List[dict])
async def list_task_boards(user_data: tuple = Depends(get_current_user)):
    current_user, _ = user_data
    boards = db.collection("taskboards").where("users", "array_contains", current_user).stream()
    return [{"id": board.id, **board.to_dict()} for board in boards]

@app.get("/taskboard/{board_id}", response_class=HTMLResponse)
async def view_task_board(board_id: str, request: Request, user_data: tuple = Depends(get_current_user)):
    current_user, token = user_data
    board_ref = db.collection("taskboards").document(board_id)
    board = board_ref.get()
    if not board.exists or current_user not in board.to_dict()["users"]:
        raise HTTPException(status_code=404, detail="Board not found or access denied")
    tasks = board_ref.collection("tasks").stream()
    task_list = [{"id": task.id, **task.to_dict()} for task in tasks]
    return templates.TemplateResponse("taskboard.html", {
        "request": request,
        "board": board.to_dict(),
        "tasks": task_list,
        "board_id": board_id,
        "is_creator": board.to_dict()["creator"] == current_user,
        "token": token  # Pass token to template
    })

@app.post("/taskboards/{board_id}/tasks/", response_model=dict)
async def create_task(board_id: str, task: TaskCreate, user_data: tuple = Depends(get_current_user)):
    current_user, _ = user_data
    board_ref = db.collection("taskboards").document(board_id)
    board = board_ref.get()
    if not board.exists or current_user not in board.to_dict()["users"]:
        raise HTTPException(status_code=403, detail="Access denied")
    task_ref = board_ref.collection("tasks").document()
    task_data = {
        "title": task.title,
        "due_date": task.due_date,
        "completed": False,
        "completed_at": None,
        "assigned_users": task.assigned_users or [],
        "created_at": datetime.now().isoformat()
    }
    task_ref.set(task_data)
    return {"id": task_ref.id, **task_data}

@app.patch("/taskboards/{board_id}/tasks/{task_id}", response_model=dict)
async def update_task(board_id: str, task_id: str, task: TaskUpdate, user_data: tuple = Depends(get_current_user)):
    current_user, _ = user_data
    board_ref = db.collection("taskboards").document(board_id)
    board = board_ref.get()
    if not board.exists or current_user not in board.to_dict()["users"]:
        raise HTTPException(status_code=403, detail="Access denied")
    task_ref = board_ref.collection("tasks").document(task_id)
    task_doc = task_ref.get()
    if not task_doc.exists:
        raise HTTPException(status_code=404, detail="Task not found")
    update_data = {}
    if task.title is not None:
        update_data["title"] = task.title
    if task.due_date is not None:
        update_data["due_date"] = task.due_date
    if task.completed is not None:
        update_data["completed"] = task.completed
        update_data["completed_at"] = datetime.now().isoformat() if task.completed else None
    if task.assigned_users is not None:
        update_data["assigned_users"] = task.assigned_users
    task_ref.update(update_data)
    return {"id": task_id, **task_ref.get().to_dict()}

@app.delete("/taskboards/{board_id}/tasks/{task_id}", status_code=204)
async def delete_task(board_id: str, task_id: str, user_data: tuple = Depends(get_current_user)):
    current_user, _ = user_data
    board_ref = db.collection("taskboards").document(board_id)
    board = board_ref.get()
    if not board.exists or current_user not in board.to_dict()["users"]:
        raise HTTPException(status_code=403, detail="Access denied")
    task_ref = board_ref.collection("tasks").document(task_id)
    if not task_ref.get().exists:
        raise HTTPException(status_code=404, detail="Task not found")
    task_ref.delete()
    return

@app.patch("/taskboards/{board_id}", response_model=dict)
async def rename_task_board(board_id: str, board: TaskBoardCreate, user_data: tuple = Depends(get_current_user)):
    current_user, _ = user_data
    board_ref = db.collection("taskboards").document(board_id)
    board_doc = board_ref.get()
    if not board_doc.exists or current_user not in board_doc.to_dict()["users"]:
        raise HTTPException(status_code=404, detail="Board not found or access denied")
    if board_doc.to_dict()["creator"] != current_user:
        raise HTTPException(status_code=403, detail="Only the creator can rename the board")
    board_ref.update({"name": board.name})
    return {"id": board_id, **board_ref.get().to_dict()}

@app.delete("/taskboards/{board_id}", status_code=204)
async def delete_task_board(board_id: str, user_data: tuple = Depends(get_current_user)):
    current_user, _ = user_data
    board_ref = db.collection("taskboards").document(board_id)
    board = board_ref.get()
    if not board.exists or current_user not in board.to_dict()["users"]:
        raise HTTPException(status_code=404, detail="Board not found or access denied")
    if board.to_dict()["creator"] != current_user:
        raise HTTPException(status_code=403, detail="Only the creator can delete the board")
    tasks = board_ref.collection("tasks").stream()
    if any(tasks):
        raise HTTPException(status_code=400, detail="Cannot delete board with existing tasks")
    if len(board.to_dict()["users"]) > 1:
        raise HTTPException(status_code=400, detail="Cannot delete board with non-owning users")
    board_ref.delete()
    return