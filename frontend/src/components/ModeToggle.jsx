import React from 'react'
import { MessageSquare, Brain } from 'lucide-react'

export default function ModeToggle({ mode, onChange }) {
  return (
    <div style={styles.wrapper}>
      <button
        style={{ ...styles.btn, ...(mode === 'chat' ? styles.active : {}) }}
        onClick={() => onChange('chat')}
      >
        <MessageSquare size={14}/>
        <span>RAG Chat</span>
        {mode === 'chat' && <span style={styles.badge}>active</span>}
      </button>
      <button
        style={{ ...styles.btn, ...(mode === 'agent' ? styles.activeAgent : {}) }}
        onClick={() => onChange('agent')}
      >
        <Brain size={14}/>
        <span>AI Agent</span>
        {mode === 'agent' && <span style={{ ...styles.badge, background: 'rgba(77,159,255,0.2)', color: 'var(--accent3)', borderColor: 'rgba(77,159,255,0.3)' }}>LangGraph</span>}
      </button>
    </div>
  )
}

const styles = {
  wrapper: {
    display: 'flex', gap: 6,
    padding: '0.75rem 2rem',
    borderBottom: '1px solid var(--border)',
    background: 'var(--surface)',
  },
  btn: {
    display: 'flex', alignItems: 'center', gap: 6,
    background: 'none', border: '1px solid var(--border)',
    borderRadius: 8, color: 'var(--text-dim)',
    fontFamily: 'Syne, sans-serif', fontWeight: 600, fontSize: '0.78rem',
    padding: '0.4rem 0.85rem', cursor: 'pointer',
    transition: 'all 0.15s',
  },
  active: {
    background: 'rgba(0,212,170,0.08)',
    borderColor: 'rgba(0,212,170,0.3)',
    color: 'var(--accent)',
  },
  activeAgent: {
    background: 'rgba(77,159,255,0.08)',
    borderColor: 'rgba(77,159,255,0.3)',
    color: 'var(--accent3)',
  },
  badge: {
    fontSize: '0.6rem', fontFamily: 'Syne, sans-serif', fontWeight: 700,
    letterSpacing: '0.08em', textTransform: 'uppercase',
    background: 'rgba(0,212,170,0.15)', color: 'var(--accent)',
    border: '1px solid rgba(0,212,170,0.25)',
    borderRadius: 4, padding: '0.05rem 0.35rem',
  },
}