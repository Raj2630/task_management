# 📝 Task Management System

A modern web-based task management app using **FastAPI**, **Firebase Authentication**, and **Firestore**. Supports signup/login, task board creation, collaborative task management, and real-time updates.

---

## 🚀 Features

- 🔐 Secure email/password authentication (Firebase)
- 🗂️ Create, rename, delete task boards (creator-only)
- ✅ Add, edit, delete, and complete tasks
- 👥 Invite/remove users for collaboration (creator-only)
- 🔢 Task counters and professional responsive UI

---

## 📁 Project Structure

task-management/ ├── static/ │ ├── style.css # Custom CSS │ └── firebase-login.js # Firebase Authentication logic ├── templates/ │ ├── index.html # Login/Signup page │ └── taskboard.html # Task Board interface ├── app.py # FastAPI backend ├── service-account.json # Firebase credentials (keep secure) ├── requirements.txt # Python dependencies └── README.md # Documentation


---

## ✅ Prerequisites

- Python 3.8+
- Firebase project with:
  - **Authentication** enabled (Email/Password)
  - **Firestore** database configured

---

## ⚙️ Setup Instructions

### 1. Clone the Repository

```bash
git clone <repository-url>
cd task-management```

### 2. Install Dependencies


```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
pip install -r requirements.txt```

### 3. Configure Firebase
Place your Firebase Admin SDK credentials in service-account.json in the project root.

Update static/firebase-login.js with your Firebase client config (from Firebase Console).

### 4. Firestore Security Rules
In Firebase Console → Firestore → Rules, paste the following:


rules_version = '2';
service cloud.firestore {
  match /databases/{database}/documents {
    match /users/{userId} {
      allow read: if request.auth != null;
      allow write: if request.auth.uid == userId;
    }
    match /taskboards/{boardId} {
      allow read, write: if request.auth.token.email in resource.data.users;
    }
  }
}

### 5. Run the App

uvicorn app:app --reload
Then open your browser and go to:

http://127.0.0.1:8000/
🧪 Usage Guide
Sign Up/Login: Use the form on the homepage with your email and password.

Create a Task Board: Enter a board name and click "Create Board".

Manage Tasks: Add, edit, delete, or complete tasks.

Collaborate: Invite/remove users (only the board creator can do this).

Sign Out: Click "Sign Out" in the navigation bar.

📦 Dependencies
🔧 Backend
fastapi

uvicorn

google-cloud-firestore

pyjwt

🎨 Frontend
Bootstrap 5.3

Firebase SDK 11.3.1

