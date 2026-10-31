import React, { useState } from 'react'
import { loginAccount, registerAccount } from '../utils/api.js'

export default function AuthPanel({ onAuthenticated }) {
  const [registering, setRegistering] = useState(false)
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  const submit = async (event) => {
    event.preventDefault()
    setBusy(true)
    setError('')
    try {
      const response = registering
        ? await registerAccount(email, password)
        : await loginAccount(email, password)
      onAuthenticated(response.data.user)
    } catch (requestError) {
      setError(requestError.response?.data?.detail || 'Could not authenticate. Check the backend configuration and try again.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <main style={styles.page}>
      <form onSubmit={submit} style={styles.card}>
        <div style={styles.brand}>FinDoc<span>AI</span></div>
        <h1 style={styles.title}>{registering ? 'Create your account' : 'Sign in'}</h1>
        <p style={styles.description}>Sign in to your secure financial document workspace.</p>
        <label style={styles.label} htmlFor="auth-email">Email</label>
        <input id="auth-email" autoComplete="email" type="email" required value={email}
          onChange={(event) => setEmail(event.target.value)} style={styles.input} />
        <label style={styles.label} htmlFor="auth-password">Password</label>
        <input id="auth-password" autoComplete={registering ? 'new-password' : 'current-password'}
          type="password" required minLength={registering ? 8 : 1} maxLength={128} value={password}
          onChange={(event) => setPassword(event.target.value)} style={styles.input} />
        {registering && <small style={styles.hint}>Use at least 8 characters.</small>}
        {error && <div role="alert" style={styles.error}>{error}</div>}
        <button type="submit" disabled={busy} style={styles.submit}>
          {busy ? 'Please wait…' : registering ? 'Create account' : 'Sign in'}
        </button>
        <button type="button" onClick={() => { setRegistering(!registering); setError('') }} style={styles.switch}>
          {registering ? 'Already have an account? Sign in' : 'New to FinDocAI? Create an account'}
        </button>
      </form>
    </main>
  )
}

const styles = {
  page: { minHeight: '100vh', display: 'grid', placeItems: 'center', background: 'var(--bg)', padding: '1rem' },
  card: { width: 'min(100%, 420px)', display: 'flex', flexDirection: 'column', gap: '0.7rem', padding: '2rem', background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 14, boxShadow: '0 16px 50px rgba(0,0,0,0.25)' },
  brand: { fontFamily: 'Syne, sans-serif', fontWeight: 800, fontSize: '1.3rem' },
  title: { margin: '0.5rem 0 0', fontFamily: 'Syne, sans-serif', fontSize: '1.5rem' },
  description: { margin: '0 0 0.5rem', color: 'var(--text-dim)', fontSize: '0.9rem' },
  label: { fontSize: '0.8rem', color: 'var(--text-dim)' },
  input: { width: '100%', boxSizing: 'border-box', padding: '0.7rem', color: 'var(--text)', background: 'var(--bg)', border: '1px solid var(--border)', borderRadius: 7 },
  hint: { color: 'var(--text-muted)' },
  error: { color: 'var(--danger)', fontSize: '0.82rem' },
  submit: { marginTop: '0.4rem', padding: '0.75rem', border: 0, borderRadius: 7, color: 'var(--bg)', background: 'var(--accent)', fontWeight: 700, cursor: 'pointer' },
  switch: { padding: '0.5rem', border: 0, color: 'var(--text-dim)', background: 'transparent', cursor: 'pointer' },
}
