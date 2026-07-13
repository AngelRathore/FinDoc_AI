import React, { useRef, useEffect } from 'react'
import ReactMarkdown from 'react-markdown'
import { Send, Bot, User, ExternalLink, TrendingUp, Loader } from 'lucide-react'

export default function ChatPanel({ messages, loading, onSend, mode }) {
  const bottomRef  = useRef()
  const inputRef   = useRef()

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, loading])

  const handleKey = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      const val = inputRef.current.value.trim()
      if (val) { onSend(val); inputRef.current.value = '' }
    }
  }

  const handleSend = () => {
    const val = inputRef.current.value.trim()
    if (val) { onSend(val); inputRef.current.value = '' }
  }

  return (
    <div style={styles.container}>
      {/* Messages */}
      <div style={styles.messages}>
        {messages.length === 0 && (
          <div style={styles.empty}>
            <Bot size={36} style={{ color: 'var(--accent)', marginBottom: 12 }}/>
            <div style={styles.emptyTitle}>
              {mode === 'agent' ? 'Financial Analysis Agent' : 'Document Chat'}
            </div>
            <div style={styles.emptyDesc}>
              {mode === 'agent'
                ? 'Ask about stocks, financial ratios, market news, or anything financial. The agent searches docs, web, and live prices automatically.'
                : 'Ask questions about your loaded documents. Answers are grounded in your sources.'}
            </div>
            <div style={styles.suggestions}>
              {mode === 'agent' ? [
                'What is the current price of AAPL?',
                'Calculate ROI: gain=5000, cost=20000',
                'Explain P/E ratio and why it matters',
                'Latest news on Indian stock market',
              ] : [
                'Summarize the key points',
                'What are the main risks mentioned?',
                'What revenue figures are discussed?',
                'Who are the key people mentioned?',
              ].map(s => (
                <button key={s} style={styles.suggBtn}
                  onClick={() => { onSend(s) }}>
                  {s}
                </button>
              ))}
            </div>
          </div>
        )}

        {messages.map((msg, i) => (
          <div key={i} style={{ ...styles.msgRow, flexDirection: msg.role === 'user' ? 'row-reverse' : 'row', animation: 'fadeUp 0.25s ease' }}>
            {/* Avatar */}
            <div style={{ ...styles.avatar, background: msg.role === 'user' ? 'var(--surface2)' : 'var(--accent)', color: msg.role === 'user' ? 'var(--text-dim)' : '#060a0d' }}>
              {msg.role === 'user' ? <User size={15}/> : <Bot size={15}/>}
            </div>

            {/* Bubble */}
            <div style={{ ...styles.bubble, background: msg.role === 'user' ? 'var(--surface2)' : 'var(--surface)', borderColor: msg.role === 'user' ? 'var(--border)' : 'rgba(0,212,170,0.15)', maxWidth: '78%' }}>
              {msg.role === 'ai' ? (
                <div className="md-content">
                  <ReactMarkdown>{msg.content}</ReactMarkdown>
                </div>
              ) : (
                <span style={{ fontSize: '0.9rem' }}>{msg.content}</span>
              )}

              {/* Agent steps */}
              {msg.steps?.length > 0 && (
                <div style={styles.steps}>
                  {msg.steps.map((step, si) => (
                    <div key={si} style={styles.step}>{step}</div>
                  ))}
                </div>
              )}

              {/* Stock data */}
              {msg.stock && (
                <div style={styles.stockCard}>
                  <TrendingUp size={13} style={{ color: 'var(--accent2)', flexShrink: 0 }}/>
                  <pre style={styles.stockPre}>{msg.stock}</pre>
                </div>
              )}

              {/* Sources */}
              {msg.sources?.length > 0 && (
                <div style={styles.sourcesBox}>
                  <span style={styles.sourcesLabel}>Sources</span>
                  {msg.sources.map((s, si) => (
                    <a key={si} href={s.startsWith('http') ? s : '#'} target="_blank" rel="noreferrer" style={styles.sourceLink}>
                      <ExternalLink size={10}/> {s.length > 55 ? s.slice(0, 53) + '…' : s}
                    </a>
                  ))}
                </div>
              )}
            </div>
          </div>
        ))}

        {/* Loading indicator */}
        {loading && (
          <div style={{ ...styles.msgRow, animation: 'fadeUp 0.25s ease' }}>
            <div style={{ ...styles.avatar, background: 'var(--accent)', color: '#060a0d' }}>
              <Bot size={15}/>
            </div>
            <div style={{ ...styles.bubble, background: 'var(--surface)', borderColor: 'rgba(0,212,170,0.15)' }}>
              <div style={styles.thinkingDots}>
                <span style={{ animationDelay: '0ms' }}/>
                <span style={{ animationDelay: '180ms' }}/>
                <span style={{ animationDelay: '360ms' }}/>
              </div>
            </div>
          </div>
        )}

        <div ref={bottomRef}/>
      </div>

      {/* Input bar */}
      <div style={styles.inputBar}>
        <textarea
          ref={inputRef}
          style={styles.textarea}
          placeholder={mode === 'agent' ? 'Ask the financial agent anything…' : 'Ask about your documents…'}
          onKeyDown={handleKey}
          rows={1}
        />
        <button style={styles.sendBtn} onClick={handleSend}>
          <Send size={16}/>
        </button>
      </div>

      <style>{`
        .thinking-dots span {
          display: inline-block; width: 7px; height: 7px;
          border-radius: 50%; background: var(--accent);
          animation: pulse 1.2s ease infinite;
          margin-right: 4px;
        }
      `}</style>
    </div>
  )
}

const styles = {
  container: {
    flex: 1, display: 'flex', flexDirection: 'column',
    height: '100vh', overflow: 'hidden',
  },
  messages: {
    flex: 1, overflowY: 'auto',
    padding: '1.5rem 2rem',
    display: 'flex', flexDirection: 'column', gap: '1rem',
  },
  empty: {
    flex: 1, display: 'flex', flexDirection: 'column', alignItems: 'center',
    justifyContent: 'center', textAlign: 'center',
    padding: '3rem 2rem', marginTop: '3rem',
  },
  emptyTitle: {
    fontFamily: 'Syne, sans-serif', fontWeight: 800, fontSize: '1.5rem',
    letterSpacing: '-0.03em', marginBottom: 8,
  },
  emptyDesc: {
    color: 'var(--text-dim)', fontSize: '0.88rem', maxWidth: 420,
    lineHeight: 1.7, marginBottom: 24,
  },
  suggestions: {
    display: 'flex', flexWrap: 'wrap', gap: 8, justifyContent: 'center',
    maxWidth: 500,
  },
  suggBtn: {
    background: 'var(--surface)', border: '1px solid var(--border)',
    borderRadius: 20, color: 'var(--text-dim)',
    fontFamily: 'DM Sans, sans-serif', fontSize: '0.8rem',
    padding: '0.4rem 0.85rem', cursor: 'pointer',
    transition: 'all 0.15s',
  },
  msgRow: {
    display: 'flex', gap: '0.75rem', alignItems: 'flex-start',
  },
  avatar: {
    width: 32, height: 32, borderRadius: '50%',
    display: 'flex', alignItems: 'center', justifyContent: 'center',
    flexShrink: 0, border: '1px solid var(--border)',
  },
  bubble: {
    border: '1px solid', borderRadius: 'var(--radius)',
    padding: '0.75rem 1rem', fontSize: '0.88rem', lineHeight: 1.55,
    maxWidth: '70%',
  },
  steps: {
    marginTop: 10, borderTop: '1px solid var(--border)', paddingTop: 8,
    display: 'flex', flexDirection: 'column', gap: 3,
  },
  step: {
    fontSize: '0.75rem', color: 'var(--text-dim)',
    fontFamily: 'DM Sans, sans-serif',
  },
  stockCard: {
    display: 'flex', gap: 8, alignItems: 'flex-start',
    background: 'rgba(240,192,64,0.06)', border: '1px solid rgba(240,192,64,0.2)',
    borderRadius: 8, padding: '0.6rem 0.8rem', marginTop: 10,
  },
  stockPre: {
    fontFamily: 'monospace', fontSize: '0.78rem', color: 'var(--accent2)',
    whiteSpace: 'pre-wrap', lineHeight: 1.6, margin: 0,
  },
  sourcesBox: {
    marginTop: 10, borderTop: '1px solid var(--border)', paddingTop: 8,
    display: 'flex', flexDirection: 'column', gap: 4,
  },
  sourcesLabel: {
    fontSize: '0.65rem', fontFamily: 'Syne, sans-serif', fontWeight: 700,
    letterSpacing: '0.1em', textTransform: 'uppercase', color: 'var(--text-muted)',
    marginBottom: 2,
  },
  sourceLink: {
    display: 'flex', alignItems: 'center', gap: 5,
    color: 'var(--accent3)', fontSize: '0.75rem', textDecoration: 'none',
  },
  thinkingDots: {
    display: 'flex', alignItems: 'center', padding: '0.1rem 0',
  },
  inputBar: {
    display: 'flex', gap: 8, padding: '1rem 2rem',
    borderTop: '1px solid var(--border)',
    background: 'var(--surface)',
    boxShadow: '0 -2px 12px rgba(0,0,0,0.04)',
  },
  textarea: {
    flex: 1, background: 'var(--surface2)', border: '1px solid var(--border)',
    borderRadius: 10, color: 'var(--text)',
    fontFamily: 'DM Sans, sans-serif', fontSize: '0.9rem',
    padding: '0.75rem 1rem', resize: 'none', outline: 'none',
    lineHeight: 1.5, boxShadow: 'inset 0 1px 3px rgba(0,0,0,0.04)',
  },
  sendBtn: {
    background: 'linear-gradient(135deg, #16a34a, #15803d)',
    color: '#fff',
    border: 'none', borderRadius: 10, cursor: 'pointer',
    width: 44, height: 44,
    display: 'flex', alignItems: 'center', justifyContent: 'center',
    flexShrink: 0, alignSelf: 'flex-end',
    boxShadow: '0 2px 8px rgba(22,163,74,0.3)',
    transition: 'all 0.15s',
  },
}