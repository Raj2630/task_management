from fastapi import FastAPI, Request, HTTPException, Depends
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from google.cloud import firestore
from google.oauth2 import id_token
from google.auth.transport import requests
import os
import logging
from datetime import datetime

app = FastAPI()
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")
logging.basicConfig(level=logging.INFO)

SERVICE_ACCOUNT_PATH = "service-account.json"
if not os.path.exists(SERVICE_ACCOUNT_PATH):
    logging.error(f"Service account file not found at: {SERVICE_ACCOUNT_PATH}")
    raise FileNotFoundError(f"Service account file not found at: {SERVICE_ACCOUNT_PATH}")
os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = SERVICE_ACCOUNT_PATH

try:
    db = firestore.Client(project="task-management-f337f")
    logging.info("Firestore client initialized successfully")
except Exception as e:
    logging.error(f"Failed to initialize Firestore client: {str(e)}")
    raise

async def get_user_data(request: Request) -> tuple:
    token = request.cookies.get("token") or request.query_params.get("token")
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    try:
        decoded = id_token.verify_firebase_token(token, requests.Request())
        logging.info(f"Decoded token: {decoded}")
        uid = decoded.get("sub")
        email = decoded.get("email")
        if not uid or not email:
            raise ValueError("Token missing required fields")
        return uid, email, token
    except ValueError as e:
        logging.error(f"Token verification failed: {str(e)}")
        raise HTTPException(status_code=401, detail="Invalid token")

@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

@app.get("/taskboards/", response_model=list)
async def list_taskboards(user_data: tuple = Depends(get_user_data)):
    uid, email, token = user_data
    try:
        boards_ref = db.collection("taskboards")
        query = boards_ref.where("users", "array_contains", email).stream()
        boards = [{"id": doc.id, **doc.to_dict(), "is_creator": doc.to_dict()["creator"] == uid} for doc in query]
        logging.info(f"Fetched {len(boards)} taskboards for user {email}")
        return boards
    except Exception as e:
        logging.error(f"Error fetching taskboards: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to fetch taskboards")

@app.post("/taskboards/")
async def create_taskboard(request: Request, user_data: tuple = Depends(get_user_data)):
    uid, email, token = user_data
    try:
        data = await request.json()
        name = data.get("name")
        if not name or db.collection("taskboards").where("name", "==", name).where("creator", "==", uid).get():
            raise HTTPException(status_code=400, detail="Invalid or duplicate board name")
        board_ref = db.collection("taskboards").document()
        board_ref.set({"name": name, "creator": uid, "users": [email]})
        logging.info(f"Created taskboard {board_ref.id} for {email}")
        return {"id": board_ref.id, "name": name}
    except Exception as e:
        logging.error(f"Error creating taskboard: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to create taskboard")

@app.get("/taskboard/{board_id}", response_class=HTMLResponse)
async def view_taskboard(request: Request, board_id: str, user_data: tuple = Depends(get_user_data)):
    uid, email, token = user_data
    try:
        board_ref = db.collection("taskboards").document(board_id)
        board = board_ref.get()
        if not board.exists or email not in board.to_dict().get("users", []):
            raise HTTPException(status_code=404, detail="Board not found or access denied")
        tasks = []
        for doc in board_ref.collection("tasks").stream():
            task_data = {"id": doc.id, **doc.to_dict()}
            if "completed_at" in task_data and task_data["completed_at"]:
                task_data["completed_at"] = task_data["completed_at"].isoformat()
            tasks.append(task_data)
        logging.info(f"Viewing taskboard {board_id} for {email}")
        return templates.TemplateResponse("taskboard.html", {
            "request": request, "board": board.to_dict(), "board_id": board_id,
            "tasks": tasks, "is_creator": board.to_dict()["creator"] == uid, "token": token,
            "current_user_email": email
        })
    except Exception as e:
        logging.error(f"Error viewing taskboard: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to view taskboard")

@app.post("/taskboards/{board_id}/tasks/")
async def add_task(board_id: str, request: Request, user_data: tuple = Depends(get_user_data)):
    uid, email, token = user_data
    try:
        board_ref = db.collection("taskboards").document(board_id)
        if not board_ref.get().exists or email not in board_ref.get().to_dict().get("users", []):
            raise HTTPException(status_code=404, detail="Board not found or access denied")
        data = await request.json()
        title, due_date, assigned_to = data.get("title"), data.get("due_date"), data.get("assigned_to")
        if not title or not due_date or db.collection("taskboards").document(board_id).collection("tasks").where("title", "==", title).get():
            raise HTTPException(status_code=400, detail="Invalid or duplicate task")
        task_ref = board_ref.collection("tasks").document()
        task_ref.set({"title": title, "due_date": due_date, "completed": False, "assigned_to": assigned_to})
        logging.info(f"Added task {task_ref.id} to board {board_id}")
        return {"id": task_ref.id}
    except Exception as e:
        logging.error(f"Error adding task: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to add task")

@app.patch("/taskboards/{board_id}")
async def rename_taskboard(board_id: str, request: Request, user_data: tuple = Depends(get_user_data)):
    uid, email, token = user_data
    try:
        board_ref = db.collection("taskboards").document(board_id)
        board = board_ref.get()
        if not board.exists or board.to_dict()["creator"] != uid:
            raise HTTPException(status_code=403, detail="Only creator can rename")
        data = await request.json()
        name = data.get("name")
        if not name or db.collection("taskboards").where("name", "==", name).where("creator", "==", uid).get():
            raise HTTPException(status_code=400, detail="Invalid or duplicate name")
        board_ref.update({"name": name})
        logging.info(f"Renamed taskboard {board_id} to {name}")
        return {"name": name}
    except Exception as e:
        logging.error(f"Error renaming taskboard: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to rename taskboard")

@app.delete("/taskboards/{board_id}")
async def delete_taskboard(board_id: str, user_data: tuple = Depends(get_user_data)):
    uid, email, token = user_data
    try:
        board_ref = db.collection("taskboards").document(board_id)
        board = board_ref.get()
        if not board.exists or board.to_dict()["creator"] != uid:
            raise HTTPException(status_code=403, detail="Only creator can delete")
        if len(board.to_dict().get("users", [])) > 1 or board_ref.collection("tasks").get():
            raise HTTPException(status_code=400, detail="Remove all users and tasks first")
        board_ref.delete()
        logging.info(f"Deleted taskboard {board_id}")
    except Exception as e:
        logging.error(f"Error deleting taskboard: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to delete taskboard")

@app.post("/taskboards/{board_id}/users")
async def invite_user(board_id: str, request: Request, user_data: tuple = Depends(get_user_data)):
    uid, email, token = user_data
    try:
        board_ref = db.collection("taskboards").document(board_id)
        board = board_ref.get()
        if not board.exists or board.to_dict()["creator"] != uid:
            raise HTTPException(status_code=403, detail="Only creator can invite")
        data = await request.json()
        new_user_email = data.get("email")
        if not new_user_email or new_user_email in board.to_dict().get("users", []):
            raise HTTPException(status_code=400, detail="Invalid or already added user")
        
        # Check if the user exists in the users collection
        users_ref = db.collection("users").where("email", "==", new_user_email).get()
        if not users_ref:
            logging.warning(f"User {new_user_email} not found in users collection")
            raise HTTPException(status_code=404, detail=f"User {new_user_email} not found. Please ensure they have signed up.")
        
        # Add the user to the taskboard
        board_ref.update({"users": firestore.ArrayUnion([new_user_email])})
        logging.info(f"Invited {new_user_email} to taskboard {board_id}")
        return {"message": f"User {new_user_email} invited successfully"}
    except HTTPException as e:
        # Pass through HTTP exceptions directly with their intended status code
        raise e
    except Exception as e:
        logging.error(f"Unexpected error inviting user: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to invite user due to an unexpected error")

@app.delete("/taskboards/{board_id}/users")
async def remove_user(board_id: str, request: Request, user_data: tuple = Depends(get_user_data)):
    uid, email, token = user_data
    try:
        board_ref = db.collection("taskboards").document(board_id)
        board = board_ref.get()
        if not board.exists or board.to_dict()["creator"] != uid:
            raise HTTPException(status_code=403, detail="Only creator can remove users")
        data = await request.json()
        user_email_to_remove = data.get("email")
        if not user_email_to_remove or user_email_to_remove not in board.to_dict().get("users", []):
            raise HTTPException(status_code=400, detail="Invalid or not a member")
        if user_email_to_remove == email:
            raise HTTPException(status_code=400, detail="Creator cannot remove themselves")
        tasks_ref = board_ref.collection("tasks")
        tasks = tasks_ref.where("assigned_to", "==", user_email_to_remove).stream()
        for task in tasks:
            tasks_ref.document(task.id).update({"assigned_to": None})
        board_ref.update({"users": firestore.ArrayRemove([user_email_to_remove])})
        logging.info(f"Removed {user_email_to_remove} from taskboard {board_id}")
    except Exception as e:
        logging.error(f"Error removing user: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to remove user")

@app.patch("/taskboards/{board_id}/tasks/{task_id}")
async def update_task(board_id: str, task_id: str, request: Request, user_data: tuple = Depends(get_user_data)):
    uid, email, token = user_data
    try:
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
        logging.info(f"Updated task {task_id} in taskboard {board_id}")
    except Exception as e:
        logging.error(f"Error updating task: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to update task")

@app.delete("/taskboards/{board_id}/tasks/{task_id}")
async def delete_task(board_id: str, task_id: str, user_data: tuple = Depends(get_user_data)):
    uid, email, token = user_data
    try:
        board_ref = db.collection("taskboards").document(board_id)
        if not board_ref.get().exists or email not in board_ref.get().to_dict().get("users", []):
            raise HTTPException(status_code=404, detail="Board not found or access denied")
        task_ref = board_ref.collection("tasks").document(task_id)
        if not task_ref.get().exists:
            raise HTTPException(status_code=404, detail="Task not found")
        task_ref.delete()
        logging.info(f"Deleted task {task_id} from taskboard {board_id}")
    except Exception as e:
        logging.error(f"Error deleting task: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to delete task")