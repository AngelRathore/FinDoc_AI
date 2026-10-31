import axios from 'axios'

const api = axios.create({ baseURL: '/api', withCredentials: true })
const TOKEN_KEY = 'findocai.auth.tokens'
let refreshPromise = null

export function getAuthTokens() {
  try {
    return JSON.parse(sessionStorage.getItem(TOKEN_KEY) || 'null')
  } catch (_) {
    return null
  }
}

export function saveAuthTokens(tokens) {
  sessionStorage.setItem(TOKEN_KEY, JSON.stringify({
    access_token: tokens.access_token,
  }))
}

export function clearAuthTokens() {
  sessionStorage.removeItem(TOKEN_KEY)
}

api.interceptors.request.use((config) => {
  const access = getAuthTokens()?.access_token
  if (access) config.headers.Authorization = `Bearer ${access}`
  return config
})

api.interceptors.response.use((response) => response, async (error) => {
  const request = error.config
  const authEndpoint = /\/auth\/(register|login|refresh|logout)(?:\?|$)/.test(request?.url || '')
  if (error.response?.status !== 401 || !request || request._retry || authEndpoint) {
    return Promise.reject(error)
  }

  if (!getAuthTokens()?.access_token) return Promise.reject(error)
  request._retry = true
  try {
    if (!refreshPromise) {
      refreshPromise = api.post('/auth/refresh')
        .then(({ data }) => {
          saveAuthTokens(data)
          return data.access_token
        })
        .finally(() => { refreshPromise = null })
    }
    const access = await refreshPromise
    request.headers.Authorization = `Bearer ${access}`
    return api(request)
  } catch (refreshError) {
    clearAuthTokens()
    window.dispatchEvent(new Event('findocai-auth-expired'))
    return Promise.reject(refreshError)
  }
})

export async function registerAccount(email, password) {
  const response = await api.post('/auth/register', { email, password })
  saveAuthTokens(response.data)
  return response
}

export async function loginAccount(email, password) {
  const response = await api.post('/auth/login', { email, password })
  saveAuthTokens(response.data)
  return response
}

export async function getCurrentUser() {
  return api.get('/auth/me')
}

export async function logoutAccount() {
  try {
    await api.post('/auth/logout')
  } finally {
    clearAuthTokens()
  }
}

// ── Ingest ─────────────────────────────────────────────────────────────────
export const ingestURLs = (urls) => api.post('/ingest/urls', { urls })

export const ingestPDFs = (files) => {
  const fd = new FormData()
  files.forEach((file) => fd.append('files', file))
  return api.post('/ingest/pdf', fd, { headers: { 'Content-Type': 'multipart/form-data' } })
}

export const ingestTXT = (files) => {
  const fd = new FormData()
  files.forEach((file) => fd.append('files', file))
  return api.post('/ingest/txt', fd, { headers: { 'Content-Type': 'multipart/form-data' } })
}

export const getIngestStatus = () => api.get('/ingest/status')
export const clearIngest = () => api.delete('/ingest/clear')
export const listDocuments = (params = {}) => api.get('/documents', { params })
export const deleteDocument = (id) => api.delete(`/documents/${id}`)
export const listAdminDocuments = (params = {}) => api.get('/documents/admin', { params })

// ── Chat ───────────────────────────────────────────────────────────────────
export const askChat = (question, conversation_id, request_id) => api.post('/chat/ask', { question, conversation_id, request_id })
export const getChatHistory = (session_id = 'default') => api.get(`/chat/history/${session_id}`)
export const clearChat = (session_id = 'default') => api.post('/chat/clear', { session_id })
export const listConversations = (params = {}) => api.get('/conversations', { params })
export const createConversation = (title) => api.post('/conversations', { title })
export const getConversation = (id, params = {}) => api.get(`/conversations/${id}`, { params })
export const renameConversation = (id, title) => api.patch(`/conversations/${id}`, { title })
export const deleteConversation = (id) => api.delete(`/conversations/${id}`)
export const sendConversationMessage = (id, question, request_id) => api.post(`/conversations/${id}/messages`, { question, request_id })

// ── Agent ──────────────────────────────────────────────────────────────────
export const runAgent = (question) => api.post('/agent/analyze', { question })
