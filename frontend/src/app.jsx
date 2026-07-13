import React, { useState, useEffect, useCallback } from 'react'
import Sidebar from './components/Sidebar.jsx'
import ChatPanel from './components/ChatPanel.jsx'
import ModeToggle from './components/ModeToggle.jsx'
import { askChat, runAgent, getIngestStatus, clearChat } from './utils/api.js'

export default function App() {
  const [mode, setMode]       = useState('chat')   // 'chat' | 'agent'
  const [messages, setMessages] = useState([])
  const [loading, setLoading] = useState(false)
  const [status, setStatus]   = useState({ ready: false, sources: [], source_count: 0 })

  // Poll ingest status on mount
  const refreshStatus = useCallback(async () => {
    try {
      const res = await getIngestStatus()
      setStatus(res.data)
    } catch (_) {}
  }, [])

  useEffect(() => {
    refreshStatus()
    const interval = setInterval(refreshStatus, 8000)
    return () => clearInterval(interval)
  }, [refreshStatus])

  // Switch mode → clear messages
  const handleModeChange = (m) => {
    setMode(m)
    setMessages([])
  }

  const handleSend = async (question) => {
    if (!question.trim()) return

    // Append user message
    setMessages(prev => [...prev, { role: 'user', content: question }])
    setLoading(true)

    try {
      if (mode === 'agent') {
        const res = await runAgent(question)
        setMessages(prev => [...prev, {
          role:    'ai',
          content: res.data.answer,
          steps:   res.data.steps  || [],
          stock:   res.data.stock  || '',
          sources: [],
        }])
      } else {
        if (!status.ready) {
          setMessages(prev => [...prev, {
            role:    'ai',
            content: '⚠️ Please load at least one source first using the sidebar.',
            sources: [],
          }])
          setLoading(false)
          return
        }
        const res = await askChat(question)
        setMessages(prev => [...prev, {
          role:    'ai',
          content: res.data.answer,
          sources: res.data.sources || [],
          steps:   [],
          stock:   '',
        }])
      }
    } catch (e) {
      setMessages(prev => [...prev, {
        role:    'ai',
        content: `⚠️ Error: ${e.response?.data?.detail || e.message}`,
        sources: [],
        steps:   [],
        stock:   '',
      }])
    } finally {
      setLoading(false)
    }
  }

  const handleClearChat = () => {
    setMessages([])
    clearChat().catch(() => {})
  }

  return (
    <div style={styles.root}>
      <Sidebar status={status} onStatusChange={refreshStatus} />

      <div style={styles.main}>
        <ModeToggle mode={mode} onChange={handleModeChange} />

        {/* Topbar */}
        <div style={styles.topbar}>
          <div>
            <div style={styles.pageTitle}>
              {mode === 'agent' ? '🤖 Financial Analysis Agent' : '💬 Document Chat'}
            </div>
            <div style={styles.pageDesc}>
              {mode === 'agent'
                ? 'LangGraph agent · live stocks · web search · calculator'
                : 'Conversational RAG · grounded answers · source citations'}
            </div>
          </div>
          {messages.length > 0 && (
            <button style={styles.clearBtn} onClick={handleClearChat}>
              Clear chat
            </button>
          )}
        </div>

        <ChatPanel
          messages={messages}
          loading={loading}
          onSend={handleSend}
          mode={mode}
        />
      </div>
    </div>
  )
}

const styles = {
  root: {
    display: 'flex', height: '100vh', overflow: 'hidden',
    background: 'var(--bg)',
  },
  main: {
    flex: 1, display: 'flex', flexDirection: 'column',
    overflow: 'hidden',
  },
  topbar: {
    display: 'flex', alignItems: 'center', justifyContent: 'space-between',
    padding: '1.2rem 2.5rem',
    borderBottom: '1px solid var(--border)',
    background: 'var(--bg)',
    boxShadow: '0 1px 8px rgba(0,0,0,0.05)',
  },
  pageTitle: {
    fontFamily: 'Syne, sans-serif', fontWeight: 800,
    fontSize: '1.6rem', letterSpacing: '-0.03em',
  },
  pageDesc: {
    fontSize: '0.82rem', color: 'var(--text-dim)', marginTop: 4,
  },
  clearBtn: {
    background: 'none', border: '1px solid var(--border)',
    borderRadius: 7, color: 'var(--text-dim)',
    fontFamily: 'DM Sans, sans-serif', fontSize: '0.78rem',
    padding: '0.35rem 0.75rem', cursor: 'pointer',
  },
}