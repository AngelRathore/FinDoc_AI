import React, { useState, useRef, useEffect, useCallback } from 'react'
import {
  Globe, FileText, Upload, Zap, Trash2,
  CheckCircle, AlertCircle, Loader, ChevronDown, ChevronUp, X, MessageSquare, Pencil
} from 'lucide-react'
import {
  ingestURLs, ingestPDFs, ingestTXT, renameConversation, deleteConversation,
  listDocuments, deleteDocument, listAdminDocuments,
} from '../utils/api'

const TAB = { URL: 'url', PDF: 'pdf', TXT: 'txt' }

export default function Sidebar({ status, onStatusChange, onConversationsChange, isAdmin = false, conversations = [], selectedConversationId, onSelectConversation, onNewConversation }) {
  const [tab, setTab]         = useState(TAB.URL)
  const [urls, setUrls]       = useState(['', '', '', '', ''])
  
  const [pdfs, setPdfs]       = useState([])
  const [txts, setTxts]       = useState([])
  const [loading, setLoading] = useState(false)
  const [msg, setMsg]         = useState(null)  // {type:'success'|'error', text}
  const [expanded, setExpanded] = useState(true)
  const [documents, setDocuments] = useState([])
  const [adminDocuments, setAdminDocuments] = useState([])
  const [adminTotal, setAdminTotal] = useState(0)
  const queuedCount = documents.filter((document) => document.status === 'queued').length
  const processingCount = documents.filter((document) => document.status === 'processing').length
  const pdfRef = useRef()
  const txtRef = useRef()

  const refreshDocuments = useCallback(async () => {
    try {
      const [ownResponse, adminResponse] = await Promise.all([
        listDocuments({ limit: 100 }),
        isAdmin ? listAdminDocuments({ limit: 100 }) : Promise.resolve(null),
      ])
      setDocuments(ownResponse.data.items || [])
      setAdminDocuments(adminResponse?.data.items || [])
      setAdminTotal(adminResponse?.data.total || 0)
    } catch (error) {
      setMsg({ type: 'error', text: error.response?.data?.detail || 'Could not load document list' })
    }
  }, [isAdmin])

  const refreshOwnedDocuments = useCallback(async () => {
    try {
      const response = await listDocuments({ limit: 100 })
      setDocuments(response.data.items || [])
      onStatusChange()
    } catch (_) {}
  }, [onStatusChange])

  const loadMoreAdminDocuments = async () => {
    try {
      const response = await listAdminDocuments({ limit: 100, offset: adminDocuments.length })
      setAdminDocuments((current) => [...current, ...(response.data.items || [])])
    } catch (error) {
      flash('error', error.response?.data?.detail || 'Could not load more uploads')
    }
  }

  useEffect(() => {
    refreshDocuments()
    const interval = setInterval(refreshOwnedDocuments, 10000)
    return () => clearInterval(interval)
  }, [refreshDocuments, refreshOwnedDocuments])

  const setUrl = (i, v) => setUrls(u => { const n=[...u]; n[i]=v; return n })
  

  const flash = (type, text) => {
    setMsg({ type, text })
    setTimeout(() => setMsg(null), 4000)
  }

  const handleProcess = async () => {
    setLoading(true)
    setMsg(null)
    try {
      if (tab === TAB.URL) {
        const valid = urls.filter(u => u.trim())
        if (!valid.length) { flash('error', 'Enter at least one URL'); setLoading(false); return }
        const res = await ingestURLs(valid)
        flash('success', `Queued ${res.data.jobs?.length || valid.length} URL(s) for background processing`)
       
      } else if (tab === TAB.PDF) {
        if (!pdfs.length) { flash('error', 'Upload at least one PDF'); setLoading(false); return }
        const res = await ingestPDFs(pdfs)
        flash('success', `Queued ${res.data.jobs?.length || pdfs.length} PDF(s) for background processing`)
      } else if (tab === TAB.TXT) {
        if (!txts.length) { flash('error', 'Upload at least one TXT file'); setLoading(false); return }
        const res = await ingestTXT(txts)
        flash('success', `Queued ${res.data.jobs?.length || txts.length} TXT file(s) for background processing`)
      }
      onStatusChange()
      refreshDocuments()
    } catch (e) {
      flash('error', e.response?.data?.detail || 'Processing failed')
    } finally {
      setLoading(false)
    }
  }

  const handleDeleteDocument = async (document) => {
    if (!window.confirm(`Delete “${document.original_filename}”? It will no longer be available for future answers.`)) return
    setLoading(true)
    try {
      await deleteDocument(document.id)
      await refreshDocuments()
      onStatusChange()
      flash('success', `Deleted ${document.original_filename}`)
    } catch (error) {
      flash('error', error.response?.data?.detail || 'Could not delete this document')
    } finally {
      setLoading(false)
    }
  }

  const tabs = [
    { id: TAB.URL, icon: Globe,     label: 'URLs'     },
    { id: TAB.PDF, icon: FileText,  label: 'PDFs'     },
    { id: TAB.TXT, icon: Upload,    label: 'TXT'      },
    
  ]

  return (
    <aside style={styles.sidebar}>
      {/* Header */}
      <div style={styles.header}>
        <div>
          <div style={styles.logo}>FinDoc<span style={{ color: 'var(--accent)' }}>AI</span></div>
          <div style={styles.logoSub}>Financial Research Agent</div>
        </div>
        <button style={styles.collapseBtn} onClick={() => setExpanded(e => !e)}>
          {expanded ? <ChevronUp size={16}/> : <ChevronDown size={16}/>}
        </button>
      </div>

      {/* Status pill */}
      <div style={{ ...styles.statusPill, background: status.ready ? 'rgba(0,212,170,0.08)' : 'rgba(255,255,255,0.03)', borderColor: status.ready ? 'rgba(0,212,170,0.3)' : 'var(--border)' }}>
        <span style={{ ...styles.dot, background: status.ready ? 'var(--accent)' : 'var(--text-muted)', boxShadow: status.ready ? '0 0 6px var(--accent)' : 'none' }}/>
        <span style={{ color: status.ready ? 'var(--accent)' : 'var(--text-dim)', fontSize: '0.8rem' }}>
          {status.ready ? `${status.source_count} source(s) loaded` : queuedCount
            ? `${queuedCount} upload(s) waiting`
            : processingCount ? `${processingCount} upload(s) processing` : 'No sources loaded'}
        </span>
      </div>

      <section style={styles.conversations}>
        <div style={styles.conversationHeading}>
          <span style={styles.sourceLabel}>Conversations</span>
          <button style={styles.newConversation} onClick={onNewConversation}>+ New</button>
        </div>
        {conversations.map((item) => (
          <div key={item.id} style={{ ...styles.conversationRow, ...(selectedConversationId === item.id ? styles.conversationSelected : {}) }}>
            <button style={styles.conversationSelect} onClick={() => onSelectConversation(item.id)} title={item.title || 'New conversation'}>
              <MessageSquare size={13} />
              <span>{item.title || 'New conversation'}</span>
            </button>
            <button style={styles.conversationAction} title="Rename" onClick={async () => {
              const title = window.prompt('Conversation name', item.title || '')
              if (title?.trim()) await renameConversation(item.id, title.trim()).then(() => onConversationsChange?.())
            }}><Pencil size={12} /></button>
            <button style={styles.conversationAction} title="Delete" onClick={async () => {
              if (window.confirm('Delete this conversation and its messages?')) await deleteConversation(item.id).then(() => onConversationsChange?.())
            }}><X size={14} /></button>
          </div>
        ))}
      </section>

      {expanded && (
        <>
          {/* Tab bar */}
          <div style={styles.tabBar}>
            {tabs.map(t => (
              <button key={t.id} style={{ ...styles.tabBtn, ...(tab === t.id ? styles.tabActive : {}) }} onClick={() => setTab(t.id)}>
                <t.icon size={13}/> {t.label}
              </button>
            ))}
          </div>

          {/* Tab content */}
          <div style={styles.tabContent}>
            {tab === TAB.URL && (
              <div style={styles.inputGroup}>
                {urls.map((u, i) => (
                  <input key={i} style={styles.input} value={u}
                    placeholder={`https://example.com/article-${i+1}`}
                    onChange={e => setUrl(i, e.target.value)} />
                ))}
              </div>
            )}

            

            {tab === TAB.PDF && (
              <div>
                <div style={styles.dropzone} onClick={() => pdfRef.current.click()}>
                  <FileText size={24} style={{ color: 'var(--text-muted)', marginBottom: 6 }}/>
                  <span style={{ color: 'var(--text-dim)', fontSize: '0.82rem' }}>
                    {pdfs.length ? `${pdfs.length} file(s) selected` : 'Click to upload PDFs'}
                  </span>
                </div>
                <input ref={pdfRef} type="file" accept=".pdf" multiple hidden
                  onChange={e => setPdfs(Array.from(e.target.files))} />
                {pdfs.map((f,i) => (
                  <div key={i} style={styles.fileTag}>
                    <FileText size={12}/> {f.name}
                    <X size={12} style={{ marginLeft: 'auto', cursor:'pointer' }}
                      onClick={() => setPdfs(p => p.filter((_,j) => j!==i))} />
                  </div>
                ))}
              </div>
            )}

            {tab === TAB.TXT && (
              <div>
                <div style={styles.dropzone} onClick={() => txtRef.current.click()}>
                  <Upload size={24} style={{ color: 'var(--text-muted)', marginBottom: 6 }}/>
                  <span style={{ color: 'var(--text-dim)', fontSize: '0.82rem' }}>
                    {txts.length ? `${txts.length} file(s) selected` : 'Click to upload TXT files'}
                  </span>
                </div>
                <input ref={txtRef} type="file" accept=".txt" multiple hidden
                  onChange={e => setTxts(Array.from(e.target.files))} />
                {txts.map((f,i) => (
                  <div key={i} style={styles.fileTag}>
                    <Upload size={12}/> {f.name}
                    <X size={12} style={{ marginLeft: 'auto', cursor:'pointer' }}
                      onClick={() => setTxts(p => p.filter((_,j) => j!==i))} />
                  </div>
                ))}
              </div>
            )}
          </div>

          {/* Message */}
          {msg && (
            <div style={{ ...styles.msgBox, borderColor: msg.type === 'success' ? 'rgba(0,212,170,0.3)' : 'rgba(255,77,109,0.3)', background: msg.type === 'success' ? 'rgba(0,212,170,0.06)' : 'rgba(255,77,109,0.06)' }}>
              {msg.type === 'success' ? <CheckCircle size={13} style={{ color: 'var(--accent)', flexShrink: 0 }}/> : <AlertCircle size={13} style={{ color: 'var(--danger)', flexShrink: 0 }}/>}
              <span style={{ fontSize: '0.78rem', color: msg.type === 'success' ? 'var(--accent)' : 'var(--danger)' }}>{msg.text}</span>
            </div>
          )}

          {/* Buttons */}
          <button style={{ ...styles.btn, opacity: loading ? 0.7 : 1 }} onClick={handleProcess} disabled={loading}>
            {loading ? <Loader size={14} style={{ animation: 'spin 1s linear infinite' }}/> : <Zap size={14}/>}
            {loading ? 'Processing…' : 'Process Sources'}
          </button>
          <div style={styles.sourceList}>
            <div style={styles.sourceLabel}>Your Documents</div>
            {queuedCount > 0 && (
              <div style={styles.ingestionNotice}>
                {queuedCount} upload(s) are queued and cannot be searched yet. Start Redis and the Celery worker with beat from the backend directory, then wait for the status to change to Ready.
              </div>
            )}
            {processingCount > 0 && (
              <div style={styles.ingestionNotice}>
                {processingCount} upload(s) are being indexed. They will become searchable when their status changes to Ready.
              </div>
            )}
            {documents.length === 0 && <div style={styles.emptyDocs}>No documents uploaded yet.</div>}
            {documents.map((document) => (
              <div key={document.id} style={styles.documentRow}>
                <div style={styles.documentInfo} title={`${document.original_filename} · ${document.status}`}>
                  <span style={styles.documentName}>{document.original_filename}</span>
                  <span style={styles.documentStatus}>
                    {document.status === 'completed' ? 'Ready' : document.status}
                    {document.status === 'failed' && document.error_message ? ` · ${document.error_message}` : ''}
                  </span>
                </div>
                <button style={styles.deleteDocumentButton} title={`Delete ${document.original_filename}`}
                  aria-label={`Delete ${document.original_filename}`} disabled={loading}
                  onClick={() => handleDeleteDocument(document)}>
                  <Trash2 size={13}/>
                </button>
              </div>
            ))}
          </div>

          {isAdmin && <div style={styles.sourceList}>
            <div style={styles.adminHeading}>
              <span style={styles.sourceLabel}>All User Uploads · Admin</span>
              <button style={styles.loadMore} onClick={refreshDocuments}>Refresh</button>
            </div>
            {adminDocuments.length === 0 && <div style={styles.emptyDocs}>No uploads found.</div>}
            {adminDocuments.map((document) => (
              <div key={document.id} style={styles.adminDocumentRow} title={document.original_filename}>
                <span style={styles.documentName}>{document.original_filename}</span>
                <span style={styles.adminUploader}>{document.owner_email}</span>
                <span style={styles.documentStatus}>{document.status}</span>
              </div>
            ))}
            {adminDocuments.length < adminTotal && <button style={styles.loadMore} onClick={loadMoreAdminDocuments}>
              Load more ({adminDocuments.length} of {adminTotal})
            </button>}
          </div>}
        </>
      )}
    </aside>
  )
}

const styles = {
  sidebar: {
    width: 280, minWidth: 280,
    background: 'var(--surface)',
    borderRight: '1px solid var(--border)',
    display: 'flex', flexDirection: 'column',
    padding: '1.2rem 1rem',
    gap: '0.75rem',
    overflowY: 'auto',
    height: '100vh',
  },
  header: {
    display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between',
  },
  logo: {
    fontFamily: 'Syne, sans-serif', fontWeight: 700, fontSize: '1.1rem',
    letterSpacing: '-0.01em', lineHeight: 1,
  },
  logoSub: {
    fontSize: '0.72rem', color: 'var(--text-dim)', marginTop: 2,
  },
  collapseBtn: {
    background: 'none', border: 'none', color: 'var(--text-muted)', cursor: 'pointer',
    padding: '2px',
  },
  statusPill: {
    display: 'flex', alignItems: 'center', gap: '0.5rem',
    padding: '0.45rem 0.75rem',
    border: '1px solid', borderRadius: 'var(--radius-sm)',
  },
  conversations: { display: 'flex', flexDirection: 'column', gap: 4, paddingBottom: 8, borderBottom: '1px solid var(--border)' },
  conversationHeading: { display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 3 },
  newConversation: { background: 'none', border: 'none', color: 'var(--accent)', cursor: 'pointer', fontSize: '0.75rem' },
  conversationRow: { display: 'flex', alignItems: 'center', borderRadius: 6, padding: '2px 4px', color: 'var(--text-dim)' },
  conversationSelected: { background: 'var(--surface2)', color: 'var(--text)' },
  conversationSelect: { display: 'flex', alignItems: 'center', gap: 7, minWidth: 0, flex: 1, border: 0, background: 'none', color: 'inherit', cursor: 'pointer', padding: '5px 2px', textAlign: 'left', fontSize: '0.75rem' },
  conversationAction: { display: 'flex', background: 'none', border: 0, color: 'var(--text-muted)', cursor: 'pointer', padding: 4 },
  dot: { width: 7, height: 7, borderRadius: '50%', flexShrink: 0 },
  tabBar: {
    display: 'flex', gap: 3,
    background: 'var(--surface2)',
    borderRadius: 'var(--radius-sm)',
    padding: 3,
  },
  tabBtn: {
    flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 4,
    background: 'none', border: 'none', cursor: 'pointer',
    color: 'var(--text-dim)', fontSize: '0.72rem',
    fontFamily: 'Syne, sans-serif', fontWeight: 600,
    padding: '0.35rem 0.2rem',
    borderRadius: 6,
    transition: 'all 0.15s',
  },
  tabActive: {
    background: 'var(--surface)', color: 'var(--accent)',
    boxShadow: '0 1px 4px rgba(0,0,0,0.3)',
  },
  tabContent: { display: 'flex', flexDirection: 'column', gap: 6 },
  inputGroup: { display: 'flex', flexDirection: 'column', gap: 6 },
  input: {
    background: 'var(--bg)', border: '1px solid var(--border)',
    borderRadius: 'var(--radius-sm)', color: 'var(--text)',
    fontFamily: 'DM Sans, sans-serif', fontSize: '0.78rem',
    padding: '0.45rem 0.65rem', outline: 'none', width: '100%',
  },
  dropzone: {
    border: '1px dashed var(--border)', borderRadius: 'var(--radius-sm)',
    padding: '1rem', textAlign: 'center', cursor: 'pointer',
    display: 'flex', flexDirection: 'column', alignItems: 'center',
    transition: 'border-color 0.15s',
    marginBottom: 6,
  },
  fileTag: {
    display: 'flex', alignItems: 'center', gap: 5,
    background: 'var(--surface2)', border: '1px solid var(--border)',
    borderRadius: 6, padding: '0.3rem 0.5rem',
    fontSize: '0.72rem', color: 'var(--text-dim)', marginBottom: 4,
  },
  msgBox: {
    display: 'flex', alignItems: 'flex-start', gap: 6,
    border: '1px solid', borderRadius: 'var(--radius-sm)',
    padding: '0.5rem 0.65rem',
  },
  btn: {
    background: 'linear-gradient(135deg, #16a34a, #15803d)',
    color: '#ffffff',
    border: 'none', borderRadius: 'var(--radius-sm)', cursor: 'pointer',
    fontFamily: 'Syne, sans-serif', fontWeight: 700, fontSize: '0.82rem',
    padding: '0.65rem', width: '100%',
    display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 6,
    transition: 'all 0.15s',
    boxShadow: '0 2px 8px rgba(22,163,74,0.25)',
  },
  btnGhost: {
    background: 'none', color: 'var(--text-dim)',
    border: '1px solid var(--border)', borderRadius: 'var(--radius-sm)', cursor: 'pointer',
    fontFamily: 'DM Sans, sans-serif', fontSize: '0.78rem',
    padding: '0.45rem', width: '100%',
    display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 5,
    transition: 'all 0.15s',
  },
  sourceList: { display: 'flex', flexDirection: 'column', gap: 4 },
  sourceLabel: {
    fontSize: '0.65rem', fontFamily: 'Syne, sans-serif', fontWeight: 700,
    letterSpacing: '0.1em', textTransform: 'uppercase', color: 'var(--text-muted)',
    marginBottom: 2,
  },
  documentRow: { display: 'flex', alignItems: 'center', gap: 6, padding: '0.3rem 0.35rem', border: '1px solid var(--border)', borderRadius: 6 },
  documentInfo: { minWidth: 0, flex: 1, display: 'flex', flexDirection: 'column', gap: 2 },
  documentName: { overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', fontSize: '0.72rem', color: 'var(--text-dim)' },
  documentStatus: { fontSize: '0.64rem', color: 'var(--text-muted)', textTransform: 'capitalize' },
  deleteDocumentButton: { display: 'flex', padding: 5, border: 0, background: 'transparent', color: 'var(--danger)', cursor: 'pointer' },
  adminDocumentRow: { display: 'flex', flexDirection: 'column', gap: 2, padding: '0.35rem', border: '1px solid var(--border)', borderRadius: 6 },
  adminHeading: { display: 'flex', alignItems: 'center', justifyContent: 'space-between' },
  adminUploader: { overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', fontSize: '0.66rem', color: 'var(--accent)' },
  emptyDocs: { fontSize: '0.72rem', color: 'var(--text-muted)', padding: '0.25rem' },
  ingestionNotice: { color: 'var(--text-dim)', fontSize: '0.72rem', lineHeight: 1.45, padding: '0.5rem', marginBottom: 4, border: '1px solid var(--border)', borderRadius: 6, background: 'rgba(255,255,255,0.025)' },
  loadMore: { border: 0, background: 'transparent', color: 'var(--accent)', cursor: 'pointer', fontSize: '0.7rem', padding: '0.35rem' },

}
