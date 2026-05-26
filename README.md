# 🧭 DataPilot — Local AI Data Assistant

> **Local-first · Zero cloud · Zero API keys · Blazing fast**

DataPilot is an AI-powered CSV and Excel analysis assistant that runs entirely on your machine. Upload data, ask questions in plain English, get charts, forecasts, summaries, and data cleaning reports — all powered by a local LLM via Ollama.

---

## ✨ Features

| Feature | Description |
|---|---|
| 💬 **Natural language Q&A** | Ask anything — gets converted to DuckDB SQL |
| 📊 **Interactive charts** | Auto-detects best chart type, renders with Plotly |
| 🔮 **Forecasting** | Holt-Winters + linear regression with confidence intervals |
| 🧹 **Data cleaning** | Detects nulls, duplicates, type mismatches, outliers |
| 📋 **Executive summaries** | LLM-generated business reports |
| 🔗 **Multi-file joins** | Query across multiple uploaded files |
| ⚡ **Sub-second queries** | DuckDB in-process SQL — no external DB needed |
| 🔒 **100% local** | Nothing leaves your machine |

---

## 🚀 Quick Start (Windows)

### Prerequisites
- **Python 3.11+** — `winget install Python.Python.3.11`
- **Node.js 18+** — `winget install OpenJS.NodeJS.LTS`
- **Ollama** (optional but recommended) — https://ollama.ai

### Run in one command
```batch
start.bat
```

This will:
1. Check for Python and Ollama
2. Create a Python virtual environment
3. Install all dependencies
4. Start FastAPI on `http://localhost:8000`
5. Start Vite on `http://localhost:5173`
6. Open your browser automatically

---

## 🧠 LLM Setup (Ollama)

```bash
# Install Ollama from https://ollama.ai, then:
ollama serve              # Start the Ollama server
ollama pull phi3:mini     # Fastest — 2GB RAM (recommended for start)
ollama pull mistral:7b    # Better quality — 5GB RAM
ollama pull llama3.1:8b   # Best quality — 8GB RAM
```

DataPilot automatically picks the best available model. If Ollama is offline, basic SQL query features still work (no natural language generation).

---

## 📁 Project Structure

```
datapilot/
├── backend/                  # FastAPI Python server
│   ├── main.py               # Entry point, routes, SSE streaming
│   ├── agents/               # One file per AI capability
│   │   ├── base_agent.py     # Abstract base with 10s timeout
│   │   ├── insight_agent.py  # NL → SQL → results
│   │   ├── clean_agent.py    # Data quality detection
│   │   ├── viz_agent.py      # Chart generation (Plotly JSON)
│   │   ├── forecast_agent.py # Time-series + linear regression
│   │   ├── summary_agent.py  # Executive summaries
│   │   ├── report_agent.py   # Full data reports
│   │   └── crossfile_agent.py# Multi-file SQL joins
│   ├── core/
│   │   ├── file_manager.py   # Upload, parse, LRU cache
│   │   ├── llm_client.py     # Ollama wrapper (streaming, fallback)
│   │   ├── data_store.py     # DuckDB in-process store
│   │   └── router.py         # Intent classification
│   └── requirements.txt
├── frontend/                 # React + Vite
│   └── src/
│       ├── App.jsx           # Main layout
│       ├── components/
│       │   ├── ChatWindow.jsx    # Chat UI with SSE streaming
│       │   ├── FileUploader.jsx  # Drag-and-drop uploader
│       │   ├── ChartRenderer.jsx # Plotly charts
│       │   └── DataPreview.jsx   # Sortable data table
│       └── hooks/
│           └── useDataPilot.js   # Zustand state store
├── docker-compose.yml        # Full containerized setup
├── start.bat                 # Windows one-click launcher
└── README.md
```

---

## 🔌 API Endpoints

| Method | Path | Description |
|---|---|---|
| `GET` | `/health` | Health check + Ollama status |
| `GET` | `/ollama/status` | Available models list |
| `POST` | `/upload` | Upload CSV/Excel file |
| `GET` | `/files` | List loaded files |
| `DELETE` | `/files/{id}` | Remove a file |
| `POST` | `/chat/stream` | SSE streaming chat |

Full interactive docs: **http://localhost:8000/docs**

---

## ⚡ Performance

| Operation | Target | Method |
|---|---|---|
| File upload + parse | < 3s (10MB) | Pandas chunked reading |
| SQL query | < 1s | DuckDB in-process |
| Chart generation | < 2s | Plotly JSON (no images) |
| LLM first token | < 500ms | SSE streaming |
| Forecast (1000 rows) | < 5s | statsmodels |

---

## 🐳 Docker (Optional)

```bash
docker-compose up -d
```

---

## 📈 Phase 2 Roadmap

- [ ] Swap Ollama → Gemini/Claude API for cloud mode
- [ ] PostgreSQL for persistent file storage
- [ ] User authentication
- [ ] Deploy to Railway/Render (backend) + Vercel (frontend)
- [ ] Excel export of query results
- [ ] Scheduled reports via email

---

## 🛠️ Dev Setup (manual)

```bash
# Backend
cd backend
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
uvicorn main:app --reload --port 8000

# Frontend (separate terminal)
cd frontend
npm install
npm run dev
```

---

## 📄 License

MIT — free to use, modify, and deploy.
