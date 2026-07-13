import axios from 'axios'

const api = axios.create({ baseURL: '/api' })

// ── Ingest ─────────────────────────────────────────────────────────────────
export const ingestURLs     = (urls)  => api.post('/ingest/urls',    { urls })

export const ingestPDFs     = (files) => {
  const fd = new FormData()
  files.forEach(f => fd.append('files', f))
  return api.post('/ingest/pdf', fd, { headers: { 'Content-Type': 'multipart/form-data' } })
}
export const ingestTXT      = (files) => {
  const fd = new FormData()
  files.forEach(f => fd.append('files', f))
  return api.post('/ingest/txt', fd, { headers: { 'Content-Type': 'multipart/form-data' } })
}
export const getIngestStatus = ()     => api.get('/ingest/status')
export const clearIngest     = ()     => api.delete('/ingest/clear')

// ── Chat ───────────────────────────────────────────────────────────────────
export const askChat       = (question, session_id = 'default') =>
  api.post('/chat/ask',  { question, session_id })
export const getChatHistory = (session_id = 'default') =>
  api.get(`/chat/history/${session_id}`)
export const clearChat     = (session_id = 'default') =>
  api.post('/chat/clear', { session_id })

// ── Agent ──────────────────────────────────────────────────────────────────
export const runAgent = (question) => api.post('/agent/analyze', { question })