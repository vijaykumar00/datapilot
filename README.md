# DataPilot 🧭

> **Local-first AI data analysis assistant** — Upload CSV/Excel, ask questions, get insights, export results.

---

## ✨ Features

| Feature | Status |
|---|---|
| Upload CSV / Excel (multi-sheet) | ✅ |
| Sheet selection & switching | ✅ |
| AI chat (Gemini / OpenAI / Claude / Ollama) | ✅ |
| Data preview & inline editing | ✅ |
| Visualizations (charts) | ✅ |
| Executive summaries & reports | ✅ |
| Forecasting | ✅ |
| Cross-file analysis | ✅ |
| Export results as CSV / XLSX | ✅ |
| Export reports as Markdown | ✅ |
| Chat session persistence (localStorage) | ✅ |
| File persistence (survives backend restarts) | ✅ |
| File rename & delete | ✅ |
| Step-by-step UI guide | ✅ |

---

## 🚀 Quick Start

### 1. Start the backend

```bash
cd backend
python -m venv venv
venv\Scripts\activate        # Windows
pip install -r requirements.txt

# Add your Gemini API key to backend/.env
# GEMINI_API_KEY=your_key_here

uvicorn main:app --host 0.0.0.0 --port 8000
```

### 2. Start the frontend

```bash
cd frontend
npm install
npm run dev
```

Open **http://localhost:5173** (or 5174 if 5173 is busy).

---

## 📋 Usage

```
1. Upload    → Drag & drop a CSV or Excel file into the sidebar
2. Sheet     → If Excel has multiple sheets, pick one from the sheet pills
3. Ask       → Type a question in the chat (e.g. "top 10 products by revenue")
4. Export    → Click "Download CSV" or "Download XLSX" under any result table
               Click "Export report" for summaries
```

---

## 🔌 API Reference

The backend exposes a REST API at `http://localhost:8000`.
Interactive docs: `http://localhost:8000/docs`

### Core endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/health` | Health check |
| `POST` | `/upload` | Upload CSV or Excel file |
| `GET` | `/files` | List loaded files |
| `GET` | `/files/{id}` | Preview file data |
| `DELETE` | `/files/{id}` | Remove file |
| `POST` | `/files/{id}/rename` | Rename a file |
| `GET` | `/files/{id}/sheets` | List Excel sheets |
| `POST` | `/files/{id}/sheet` | Switch active sheet |
| `POST` | `/chat/stream` | SSE streaming chat |
| `GET` | `/export/file/{id}` | Download full dataset |
| `POST` | `/export/results` | Export query results |
| `POST` | `/export/report` | Export narrative report |
| `GET` | `/provider` | Current AI provider |
| `POST` | `/provider` | Switch AI provider |
| `DELETE` | `/session/{id}` | Clear chat session |

---

## 🔑 AI Providers

Set in `backend/.env`:

```env
# Gemini (default — free tier at aistudio.google.com)
GEMINI_API_KEY=your_key
GEMINI_MODEL=models/gemini-2.5-flash

# OpenAI (optional)
OPENAI_API_KEY=your_key

# Claude (optional)
ANTHROPIC_API_KEY=your_key

# Ollama local (optional — run ollama separately)
OLLAMA_MODEL=llama3.2
```

Switch providers at runtime via the UI sidebar — no restart needed.

---

## 🗂️ Project Structure

```
datapilot/
├── backend/
│   ├── main.py              # FastAPI app + all routes
│   ├── core/
│   │   ├── file_manager.py  # Upload, parse, persist, sheet switching
│   │   ├── data_store.py    # DuckDB query engine
│   │   ├── llm_client.py    # Multi-provider LLM factory
│   │   ├── session_store.py # Chat session history (in-memory, TTL 24h)
│   │   └── router.py        # Intent classifier
│   ├── agents/              # Insight, Viz, Forecast, Clean, Summary, Report, CrossFile
│   └── uploads/             # Persisted uploaded files (auto-reloaded on restart)
└── frontend/
    ├── src/
    │   ├── App.jsx
    │   ├── components/
    │   │   ├── ChatWindow.jsx
    │   │   ├── DataPreview.jsx
    │   │   ├── FileUploader.jsx   # With inline rename + SheetSelector
    │   │   ├── SheetSelector.jsx
    │   │   ├── StepIndicator.jsx
    │   │   ├── ProviderSelector.jsx
    │   │   └── ChartRenderer.jsx
    │   └── hooks/
    │       └── useDataPilot.js    # Zustand store + localStorage persistence
    └── vite.config.js
```
