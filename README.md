# CodeLENSE

CodeLENSE is a Flask-based Python learning workspace with a code editor, Python execution, AST inspection, and heuristic time/space complexity analysis.

## Run locally

```powershell
cd python_frontend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python app.py
```

Open `http://127.0.0.1:5173`.

## Deploy from GitHub

GitHub Pages only serves static files and cannot run this Flask backend. This repository includes a Render Blueprint at `render.yaml`; create a Blueprint service in Render and select this GitHub repository. Render will install the Python dependencies, start Gunicorn, and deploy subsequent pushes to `main` automatically.

The Blueprint generates `DEMO_ACCESS_CODE`. When prompted by the browser, use username `demo` and the access code shown in the Render service's environment settings. Share that code only with the intended audience. It protects the public Python execution endpoints from anonymous use; this educational code runner is not a hardened sandbox for confidential or hostile code.

The free Render service may sleep when idle, so the first visit after inactivity can take a little longer. Complexity results are static-analysis estimates, not formal proofs.

## Tests

```powershell
cd python_frontend
python -m pytest test_app.py -q
```