from fastapi import FastAPI, Request, HTTPException, Depends
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from google.cloud import firestore
from google.oauth2 import id_token
from google.auth.transport import requests
import os
import logging

app = FastAPI()
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")
os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = "service-account.json"
db = firestore.Client()
logging.basicConfig(level=logging.INFO)

async def get_user_data(request: Request) -> tuple:
    token = request.cookies.get("token") or request.query_params.get("token")
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    try:
        decoded = id_token.verify_firebase_token(token, requests.Request())
        logging.info(f"Decoded token: {decoded}")
        uid = decoded.get("sub")  # Firebase uses 'sub' for user ID
        email = decoded.get("email")
        if not uid or not email:
            raise ValueError("Token missing required fields")
        return uid, email
    except ValueError as e:
        logging.error(f"Token verification failed: {str(e)}")
        raise HTTPException(status_code=401, detail="Invalid token")

@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

@app.get("/taskboards/", response_model=list)
async def list_taskboards(user_data: tuple = Depends(get_user_data)):
    uid, email = user_data
    boards_ref = db.collection("taskboards")
    query = boards_ref.where("users", "array_contains", email).stream()
    boards = [{"id": doc.id, **doc.to_dict(), "is_creator": doc.to_dict()["creator"] == uid} for doc in query]
    return boards

@app.post("/taskboards/")
async def create_taskboard(request: Request, user_data: tuple = Depends(get_user_data)):
    uid, email = user_data
    data = await request.json()
    name = data.get("name")
    if not name or db.collection("taskboards").where("name", "==", name).where("creator", "==", uid).get():
        raise HTTPException(status_code=400, detail="Invalid or duplicate board name")
    board_ref = db.collection("taskboards").document()
    board_ref.set({"name": name, "creator": uid, "users": [email]})
    return {"id": board_ref.id, "name": name}

@app.get("/taskboard/{board_id}", response_class=HTMLResponse)
async def view_taskboard(request: Request, board_id: str, user_data: tuple = Depends(get_user_data)):
    uid, email = user_data
    board_ref = db.collection("taskboards").document(board_id)
    board = board_ref.get()
    if not board.exists or email not in board.to_dict().get("users", []):
        raise HTTPException(status_code=404, detail="Board not found or access denied")
    tasks = [{"id": doc.id, **doc.to_dict()} for doc in board_ref.collection("tasks").stream()]
    return templates.TemplateResponse("taskboard.html", {
        "request": request, "board": board.to_dict(), "board_id": board_id,
        "tasks": tasks, "is_creator": board.to_dict()["creator"] == uid, "token": request.query_params.get("token")
    })

@app.post("/taskboards/{board_id}/tasks/")
async def add_task(board_id: str, request: Request, user_data: tuple = Depends(get_user_data)):
    uid, email = user_data
    board_ref = db.collection("taskboards").document(board_id)
    if not board_ref.get().exists or email not in board_ref.get().to_dict().get("users", []):
        raise HTTPException(status_code=404, detail="Board not found or access denied")
    data = await request.json()
    title, due_date, assigned_to = data.get("title"), data.get("due_date"), data.get("assigned_to")
    if not title or not due_date or db.collection("taskboards").document(board_id).collection("tasks").where("title", "==", title).get():
        raise HTTPException(status_code=400, detail="Invalid or duplicate task")
    task_ref = board_ref.collection("tasks").document()
    task_ref.set({"title": title, "due_date": due_date, "completed": False, "assigned_to": assigned_to})
    return {"id": task_ref.id}

@app.patch("/taskboards/{board_id}")
async def rename_taskboard(board_id: str, request: Request, user_data: tuple = Depends(get_user_data)):
    uid, email = user_data
    board_ref = db.collection("taskboards").document(board_id)
    board = board_ref.get()
    if not board.exists or board.to_dict()["creator"] != uid:
        raise HTTPException(status_code=403, detail="Only creator can rename")
    data = await request.json()
    name = data.get("name")
    if not name or db.collection("taskboards").where("name", "==", name).where("creator", "==", uid).get():
        raise HTTPException(status_code=400, detail="Invalid or duplicate name")
    board_ref.update({"name": name})
    return {"name": name}

@app.delete("/taskboards/{board_id}")
async def delete_taskboard(board_id: str, user_data: tuple = Depends(get_user_data)):
    uid, email = user_data
    board_ref = db.collection("taskboards").document(board_id)
    board = board_ref.get()
    if not board.exists or board.to_dict()["creator"] != uid:
        raise HTTPException(status_code=403, detail="Only creator can delete")
    if len(board.to_dict().get("users", [])) > 1 or board_ref.collection("tasks").get():
        raise HTTPException(status_code=400, detail="Remove all users and tasks first")
    board_ref.delete()

@app.post("/taskboards/{board_id}/users")
async def invite_user(board_id: str, request: Request, user_data: tuple = Depends(get_user_data)):
    uid, email = user_data
    board_ref = db.collection("taskboards").document(board_id)
    board = board_ref.get()
    if not board.exists or board.to_dict()["creator"] != uid:
        raise HTTPException(status_code=403, detail="Only creator can invite")
    data = await request.json()
    new_user_email = data.get("email")
    if not new_user_email or new_user_email in board.to_dict().get("users", []):
        raise HTTPException(status_code=400, detail="Invalid or already added user")
    users_ref = db.collection("users").where("email", "==", new_user_email).get()
    if not users_ref:
        raise HTTPException(status_code=404, detail="User not found")
    board_ref.update({"users": firestore.ArrayUnion([new_user_email])})

@app.patch("/taskboards/{board_id}/tasks/{task_id}")
async def update_task(board_id: str, task_id: str, request: Request, user_data: tuple = Depends(get_user_data)):
    uid, email = user_data
    board_ref = db.collection("taskboards").document(board_id)
    if not board_ref.get().exists or email not in board_ref.get().to_dict().get("users", []):
        raise HTTPException(status_code=404, detail="Board not found or access denied")
    task_ref = board_ref.collection("tasks").document(task_id)
    if not task_ref.get().exists:
        raise HTTPException(status_code=404, detail="Task not found")
    data = await request.json()
    updates = {}
    if "title" in data and data["title"]:
        if db.collection("taskboards").document(board_id).collection("tasks").where("title", "==", data["title"]).get():
            raise HTTPException(status_code=400, detail="Duplicate task title")
        updates["title"] = data["title"]
    if "due_date" in data and data["due_date"]:
        updates["due_date"] = data["due_date"]
    if "completed" in data:
        updates["completed"] = data["completed"]
        if data["completed"]:
            updates["completed_at"] = firestore.SERVER_TIMESTAMP
        else:
            updates["completed_at"] = None
    if "assigned_to" in data:
        updates["assigned_to"] = data["assigned_to"]
    task_ref.update(updates)

@app.delete("/taskboards/{board_id}/tasks/{task_id}")
async def delete_task(board_id: str, task_id: str, user_data: tuple = Depends(get_user_data)):
    uid, email = user_data
    board_ref = db.collection("taskboards").document(board_id)
    if not board_ref.get().exists or email not in board_ref.get().to_dict().get("users", []):
        raise HTTPException(status_code=404, detail="Board not found or access denied")
    task_ref = board_ref.collection("tasks").document(task_id)
    if not task_ref.get().exists:
        raise HTTPException(status_code=404, detail="Task not found")
    task_ref.delete()