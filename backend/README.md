# Backend - FastAPI Server

## Setup

```bash
cd backend
python -m venv venv

# Activate virtual environment
# Windows:
venv\Scripts\activate
# Linux/Mac:
source venv/bin/activate

pip install -r requirements.txt
```

## Run Development Server

```bash
uvicorn app.main:app --reload --port 8000
```

API docs available at: `http://localhost:8000/docs`

## Project Structure

```
backend/
├── app/
│   ├── api/
│   │   └── routes/           # API endpoints per component
│   ├── models/               # Pydantic schemas & data models
│   ├── services/             # Business logic & ML inference
│   ├── core/                 # Config, auth, dependencies
│   └── main.py               # App entry point
├── tests/                    # Unit & integration tests
└── requirements.txt
```
