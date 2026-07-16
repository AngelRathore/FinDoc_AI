# 🤖 FinDocAI - Agentic RAG-Based Financial Document Intelligence System

An intelligent financial document assistant powered by **Agentic AI**, **Retrieval-Augmented Generation (RAG)**, and **LangGraph**. FinDocAI enables users to upload financial documents, ask natural language questions, retrieve accurate context from documents, perform live web searches, fetch stock information, and maintain conversational memory through an intelligent multi-agent workflow.

---

## 🚀 Features

- 📄 Upload and analyze PDFs, TXT files, and URLs
- 🧠 Agentic AI workflow using LangGraph
- 🔍 Semantic document retrieval using FAISS
- 🌐 Live web search for recent financial information
- 📈 Stock market data retrieval using Yahoo Finance
- 💬 Multi-turn conversations with chat memory
- ⚡ FastAPI backend with REST APIs
- 🎨 React frontend for an interactive chat experience
- 📚 Automatic document chunking and embedding generation
- 🔄 Intelligent routing between multiple tools based on user queries

---

## 🏗️ Architecture

```
                  User Query
                      │
                      ▼
              LangGraph Agent
                      │
        ┌─────────────┼─────────────┐
        │             │             │
        ▼             ▼             ▼
 Document Search   Web Search   Finance Tool
   (FAISS)                        (Yahoo Finance)
        │             │             │
        └─────────────┼─────────────┘
                      ▼
              Groq LLM (Llama 3.1)
                      │
                      ▼
               Final Response
```

---

## 🛠️ Tech Stack

### Backend
- Python
- FastAPI
- LangChain
- LangGraph
- FAISS
- Hugging Face Sentence Transformers
- Groq API
- Pydantic

### Frontend
- React.js
- JavaScript
- HTML/CSS

### AI & ML
- Retrieval-Augmented Generation (RAG)
- Agentic AI
- Semantic Search
- Vector Embeddings
- Conversational Memory

### External Tools
- Yahoo Finance API
- Web Search API

---

## 📂 Project Structure

```
FinDocAI
│
├── backend
│   ├── routers
│   │   ├── ingest.py
│   │   ├── chat.py
│   │   └── agent.py
│   │
│   ├── utils
│   ├── vectorstore
│   ├── uploads
│   └── main.py
│
├── frontend
│   ├── src
│   ├── public
│   └── package.json
│
├── requirements.txt
└── README.md
```

---

## ⚙️ How It Works

### 1. Document Ingestion

- Upload PDF, TXT files, or URLs
- Extract text
- Split into chunks
- Generate embeddings using Hugging Face
- Store embeddings in FAISS

---

### 2. User Query

The user asks a question through the chat interface.

Example:

> "Summarize Tesla's Q4 earnings."

---

### 3. Intelligent Routing

The LangGraph agent decides whether the query requires:

- Document Retrieval
- Live Web Search
- Stock Market Tool
- Multiple tools together

---

### 4. Context Retrieval

Relevant document chunks are retrieved from FAISS using semantic similarity.

---

### 5. LLM Response

The retrieved context is combined with the user's query and passed to **Groq Llama 3.1**, which generates an accurate and context-aware response.

---

## 📦 Installation

Clone the repository

```bash
git clone https://github.com/yourusername/FinDocAI.git

cd FinDocAI
```

Create virtual environment

```bash
python -m venv venv
```

Activate

Windows

```bash
venv\Scripts\activate
```

Mac/Linux

```bash
source venv/bin/activate
```

Install dependencies

```bash
pip install -r requirements.txt
```

---

## 🔑 Environment Variables

Create a `.env` file.

```text
GROQ_API_KEY=your_groq_api_key

HUGGINGFACE_API_KEY=your_huggingface_key

TAVILY_API_KEY=your_search_api_key
```

---

## ▶️ Run Backend

```bash
uvicorn main:app --reload
```

Backend will start at

```
http://localhost:8000
```

---

## ▶️ Run Frontend

```bash
cd frontend

npm install

npm start
```

Frontend runs on

```
http://localhost:3000
```

---

## 📸 Demo

### Upload Documents

- PDF
- TXT
- URLs

### Ask Questions

Examples

```
Summarize this annual report.

What are the company's major risks?

What was Tesla's revenue growth?

Compare Apple and Microsoft.

What is the latest news about NVIDIA?
```

---

## 🎯 Example Workflow

```
Upload PDF
        │
        ▼
Text Extraction
        │
        ▼
Chunking
        │
        ▼
Embeddings
        │
        ▼
FAISS Vector Store
        │
        ▼
User Question
        │
        ▼
LangGraph Agent
        │
 ┌──────┼────────┐
 │      │        │
 ▼      ▼        ▼
FAISS  Web     Finance
 │      │        │
 └──────┼────────┘
        ▼
Groq LLM
        ▼
Answer
```

---

## ✨ Key Highlights

- Agentic AI architecture using LangGraph
- Corrective RAG pipeline
- Multi-tool intelligent routing
- Semantic vector search
- Conversational memory
- Financial document analysis
- Live financial data integration
- Modular FastAPI backend
- Scalable architecture

---

## 🔮 Future Improvements

- OCR support for scanned PDFs
- Citation generation
- Multi-user authentication
- Cloud vector database
- Streaming responses
- Docker deployment
- Evaluation using RAGAS
- Document versioning

---

## 👨‍💻 Author

**Angel Rathore**

Computer Science Undergraduate | AI & Machine Learning | Backend Development

---

## ⭐ If you found this project useful, consider giving it a star!
