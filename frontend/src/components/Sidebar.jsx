import React, { useState, useRef } from 'react'
import {
  Globe, FileText, Upload, Zap, Trash2,
  CheckCircle, AlertCircle, Loader, ChevronDown, ChevronUp, X
} from 'lucide-react'
import {
  ingestURLs, ingestPDFs, ingestTXT, clearIngest
} from '../utils/api'

const TAB = { URL: 'url', PDF: 'pdf', TXT: 'txt' }

export default function Sidebar({ status, onStatusChange }) {
  const [tab, setTab]         = useState(TAB.URL)
  const [urls, setUrls]       = useState(['', '', '', '', ''])
  
  const [pdfs, setPdfs]       = useState([])
  const [txts, setTxts]       = useState([])
  const [loading, setLoading] = useState(false)
  const [msg, setMsg]         = useState(null)  // {type:'success'|'error', text}
  const [expanded, setExpanded] = useState(true)
  const pdfRef = useRef()
  const txtRef = useRef()

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
        flash('success', `✅ Indexed ${res.data.chunks} chunks from ${valid.length} URL(s)`)
       
      } else if (tab === TAB.PDF) {
        if (!pdfs.length) { flash('error', 'Upload at least one PDF'); setLoading(false); return }
        const res = await ingestPDFs(pdfs)
        flash('success', `✅ Indexed ${res.data.chunks} chunks from ${pdfs.length} PDF(s)`)
      } else if (tab === TAB.TXT) {
        if (!txts.length) { flash('error', 'Upload at least one TXT file'); setLoading(false); return }
        const res = await ingestTXT(txts)
        flash('success', `✅ Indexed ${res.data.chunks} chunks from ${txts.length} file(s)`)
      }
      onStatusChange()
    } catch (e) {
      flash('error', e.response?.data?.detail || 'Processing failed')
    } finally {
      setLoading(false)
    }
  }

  const handleClear = async () => {
    await clearIngest()
    setUrls(['','','','',''])
    
    setPdfs([])
    setTxts([])
    onStatusChange()
    flash('success', 'Sources cleared')
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
          {status.ready ? `${status.source_count} source(s) loaded` : 'No sources loaded'}
        </span>
      </div>

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
          <button style={styles.btnGhost} onClick={handleClear}>
            <Trash2 size={13}/> Clear All
          </button>

          {/* Loaded sources list */}
          {status.sources?.length > 0 && (
            <div style={styles.sourceList}>
              <div style={styles.sourceLabel}>Loaded Sources</div>
              {status.sources.map((s, i) => (
                <div key={i} style={styles.sourceItem}>
                  <span style={{ color: 'var(--accent)', flexShrink: 0 }}>·</span>
                  <span style={{ fontSize: '0.73rem', color: 'var(--text-dim)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                    {s.length > 40 ? s.slice(0, 38) + '…' : s}
                  </span>
                </div>
              ))}
            </div>
          )}
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
  sourceItem: { display: 'flex', alignItems: 'center', gap: 5 },

  sidebar: {
    width: 260, minWidth: 260,
    background: 'var(--surface)',
    borderRight: '1px solid var(--border)',
    boxShadow: '2px 0 12px rgba(0,0,0,0.06)',
    display: 'flex', flexDirection: 'column',
    padding: '1.4rem 1.1rem',
    gap: '0.75rem',
    overflowY: 'auto',
    height: '100vh',
  },
}