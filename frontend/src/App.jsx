import React, { useState, useEffect, useCallback, useRef } from 'react'
import Sidebar from './components/Sidebar.jsx'
import ChatPanel from './components/ChatPanel.jsx'
import AuthPanel from './components/AuthPanel.jsx'
import {
  askChat, getIngestStatus, listConversations, createConversation, getConversation,
  getAuthTokens, getCurrentUser, clearAuthTokens, logoutAccount,
} from './utils/api.js'

const toUiMessages = (rows = []) => rows.map((item) => ({
  id: item.id,
  role: item.role === 'assistant' ? 'ai' : 'user',
  content: item.content,
  status: item.status,
  sources: (item.citations || []).map((citation) => ({
    text: `${citation.reference} ${citation.source}${citation.page != null ? ` (page ${citation.page + 1})` : ''}`,
    available: citation.available !== false,
  })),
}))

export default function App() {
  const [messages, setMessages] = useState([])
  const [loading, setLoading] = useState(false)
  const [status, setStatus] = useState({ ready: false, sources: [], source_count: 0 })
  const [user, setUser] = useState(null)
  const [authReady, setAuthReady] = useState(false)
  const [conversations, setConversations] = useState([])
  const [selectedConversationId, setSelectedConversationId] = useState(null)
  const viewVersion = useRef(0)
  const sending = useRef(false)

  useEffect(() => {
    if (!getAuthTokens()?.access_token) { setAuthReady(true); return }
    getCurrentUser().then(res => setUser(res.data)).catch(() => clearAuthTokens()).finally(() => setAuthReady(true))
  }, [])

  useEffect(() => {
    const expireSession = () => {
      viewVersion.current += 1
      clearAuthTokens()
      setUser(null)
      setMessages([])
      setConversations([])
      setSelectedConversationId(null)
    }
    window.addEventListener('findocai-auth-expired', expireSession)
    return () => window.removeEventListener('findocai-auth-expired', expireSession)
  }, [])

  const refreshStatus = useCallback(async () => {
    if (!user) return
    try { setStatus((await getIngestStatus()).data) } catch (_) {}
  }, [user])

  useEffect(() => {
    if (!user) return undefined
    refreshStatus()
    const interval = setInterval(refreshStatus, 8000)
    return () => clearInterval(interval)
  }, [refreshStatus, user])

  const refreshConversations = useCallback(async () => {
    if (!user) return []
    const rows = (await listConversations({ limit: 100 })).data.items
    setConversations(rows)
    return rows
  }, [user])

  const openConversation = useCallback(async (id) => {
    const version = ++viewVersion.current
    setSelectedConversationId(id)
    setMessages([])
    setLoading(false)
    try {
      const detail = (await getConversation(id, { limit: 100 })).data
      if (viewVersion.current === version) setMessages(toUiMessages(detail.messages))
    } catch (_) {
      if (viewVersion.current === version) setMessages([{ role: 'ai', content: 'Could not load this conversation.', sources: [] }])
    }
  }, [])

  useEffect(() => {
    if (!user) return
    let cancelled = false
    ;(async () => {
      try {
        const rows = await refreshConversations()
        if (cancelled) return
        if (rows.length) await openConversation(rows[0].id)
        else {
          const created = (await createConversation()).data
          if (cancelled) return
          setConversations([created])
          await openConversation(created.id)
        }
      } catch (_) {}
    })()
    return () => { cancelled = true }
  }, [user, refreshConversations, openConversation])

  const handleNewConversation = async () => {
    const created = (await createConversation()).data
    setConversations(rows => [created, ...rows])
    await openConversation(created.id)
  }

  const handleConversationListChange = async () => {
    const rows = await refreshConversations()
    if (!rows.some(item => item.id === selectedConversationId)) {
      if (rows.length) await openConversation(rows[0].id)
      else await handleNewConversation()
    }
  }

  const handleLogout = async () => {
    viewVersion.current += 1
    await logoutAccount().catch(() => {})
    setUser(null)
    setMessages([])
    setConversations([])
    setSelectedConversationId(null)
    setStatus({ ready: false, sources: [], source_count: 0 })
  }

  const handleSend = async (question) => {
    if (sending.current || !question.trim() || !selectedConversationId) return
    sending.current = true
    const version = viewVersion.current
    const conversationId = selectedConversationId
    const requestId = globalThis.crypto?.randomUUID?.() || `${Date.now()}-${Math.random()}`
    setMessages(prev => [...prev, { role: 'user', content: question }])
    setLoading(true)
    try {
      const res = await askChat(question, conversationId, requestId)
      if (viewVersion.current === version) {
        setMessages(prev => [...prev, { id: res.data.message_id, role: 'ai', content: res.data.answer,
          sources: res.data.citations?.length ? res.data.citations.map((citation) => ({
            text: `${citation.reference} ${citation.source}${citation.page != null ? ` (page ${citation.page + 1})` : ''}`,
            available: citation.available !== false,
          })) : (res.data.sources || []), citations: res.data.citations || [], steps: [], stock: '' }])
      }
      await refreshConversations()
    } catch (e) {
      if (viewVersion.current === version) setMessages(prev => [...prev, {
        role: 'ai', content: `⚠️ Error: ${e.response?.data?.detail || e.message}`, sources: [],
      }])
    } finally {
      sending.current = false
      if (viewVersion.current === version) setLoading(false)
    }
  }

  if (!authReady) return <div style={{ minHeight: '100vh', background: 'var(--bg)' }} />
  if (!user) return <AuthPanel onAuthenticated={setUser} />

  return (
    <div style={styles.root}>
      <Sidebar status={status} onStatusChange={refreshStatus} onConversationsChange={handleConversationListChange}
        conversations={conversations} selectedConversationId={selectedConversationId}
        onSelectConversation={openConversation} onNewConversation={handleNewConversation}
        isAdmin={user.role === 'admin'} />
      <div style={styles.main}>
        <div style={styles.topbar}>
          <div>
            <div style={styles.pageTitle}>💬 Document Chat</div>
            <div style={styles.pageDesc}>Conversational RAG · grounded answers · source citations</div>
          </div>
          <div style={styles.topbarActions}>
            <span style={styles.userLabel}>{user.email}</span>
            <button style={styles.clearBtn} onClick={handleLogout}>Sign out</button>
          </div>
        </div>
        <ChatPanel messages={messages} loading={loading} onSend={handleSend} mode="chat" />
      </div>
    </div>
  )
}

const styles = {
  root: { display: 'flex', height: '100vh', overflow: 'hidden', background: 'var(--bg)' },
  main: { flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden' },
  topbar: { display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '1.2rem 2.5rem', borderBottom: '1px solid var(--border)', background: 'var(--bg)', boxShadow: '0 1px 8px rgba(0,0,0,0.05)' },
  topbarActions: { display: 'flex', alignItems: 'center', gap: '0.75rem' },
  userLabel: { color: 'var(--text-dim)', fontSize: '0.78rem' },
  pageTitle: { fontFamily: 'Syne, sans-serif', fontWeight: 800, fontSize: '1.6rem', letterSpacing: '-0.03em' },
  pageDesc: { fontSize: '0.82rem', color: 'var(--text-dim)', marginTop: 4 },
  clearBtn: { background: 'none', border: '1px solid var(--border)', borderRadius: 7, color: 'var(--text-dim)', fontFamily: 'DM Sans, sans-serif', fontSize: '0.78rem', padding: '0.35rem 0.75rem', cursor: 'pointer' },
}
