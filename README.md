# SupportIQ AI — Windows Edition

## Frontend
```powershell
cd frontend
npm install
npm run dev
```
Open http://localhost:5173

## Backend
```powershell
cd backend
python -m venv venv
venv\Scripts\Activate.ps1
pip install -r requirements.txt
uvicorn app.main:app --reload
```
Open http://127.0.0.1:8000/docs
