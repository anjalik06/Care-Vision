# Care Vision

Patient emotion monitoring split into three parts:

- `frontend/` - React UI built with Vite.
- `backend/` - Flask API, SQLite database, patient records, and video-feed proxy.
- `fer_service/` - Separate camera/emotion process that streams video and posts emotion records to the backend.

Shared runtime data:

- `patient_photos/` - face reference photos used by both backend uploads and the FER service.
- `backend/instance/patients.db` - SQLite database.

## Run

Install Python dependencies:

```bash
pip install -r backend/requirements.txt
pip install -r fer_service/requirements.txt
```

Install frontend dependencies:

```bash
cd frontend
npm install
```

Start the backend API:

```bash
python backend/app.py
```

Start the FER service in another terminal:

```bash
python fer_service/main.py
```

Start the React frontend in another terminal:

```bash
cd frontend
npm run dev
```

The frontend expects the API at `http://localhost:5000/api`. Override it with `VITE_API_URL` if needed.
