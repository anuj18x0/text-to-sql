import { useState, useEffect } from 'react'
import ChatWindow from './components/ChatWindow'
import SchemaExplorer from './components/SchemaExplorer'
import MetricsDashboard from './components/MetricsDashboard'
import ApprovalModal from './components/ApprovalModal'
import { getSchema, postApprove, type SchemaTable, type QueryResponse } from './api'

export interface Message {
  id: string
  type: 'question' | 'answer' | 'error'
  content: QueryResponse | string
  timestamp: Date
}

type View = 'chat' | 'dashboard'

export default function App() {
  const [messages, setMessages] = useState<Message[]>([])
  const [schema, setSchema] = useState<SchemaTable[]>([])
  const [activeTables, setActiveTables] = useState<string[]>([])
  const [pendingApproval, setPendingApproval] = useState<QueryResponse | null>(null)
  const [activeView, setActiveView] = useState<View>('chat')

  useEffect(() => {
    getSchema()
      .then(setSchema)
      .catch((err) => console.error('Failed to load schema:', err))
  }, [])

  const handleAnswer = (response: QueryResponse) => {
    if (response.requires_approval) {
      setPendingApproval(response)
    }
    setActiveTables(response.tables_used)
  }

  const handleApprove = async (approved: boolean) => {
    if (!pendingApproval) return
    try {
      const result = await postApprove(pendingApproval.sql, approved)
      const updatedResponse: QueryResponse = {
        ...pendingApproval,
        results: result.results,
        requires_approval: false,
      }
      setMessages((prev) => [
        ...prev,
        {
          id: crypto.randomUUID(),
          type: 'answer',
          content: updatedResponse,
          timestamp: new Date(),
        },
      ])
    } catch (err) {
      console.error('Approval failed:', err)
    } finally {
      setPendingApproval(null)
    }
  }

  return (
    <div style={{
      display: 'flex',
      height: '100vh',
      overflow: 'hidden',
      background: 'var(--bg-primary)',
    }}>
      {/* Sidebar */}
      <div style={{
        width: '280px',
        minWidth: '280px',
        borderRight: '1px solid var(--border-color)',
        overflow: 'hidden',
        display: 'flex',
        flexDirection: 'column',
      }}>
        {/* Logo */}
        <div style={{
          padding: '16px',
          borderBottom: '1px solid var(--border-color)',
          fontFamily: 'var(--font-mono)',
          color: 'var(--accent-green)',
          fontSize: '14px',
          fontWeight: 700,
          letterSpacing: '0.05em',
        }}>
          ⚡ TEXT-TO-SQL
        </div>

        {/* View Toggle */}
        <div style={{
          display: 'flex',
          padding: '8px',
          gap: '4px',
          borderBottom: '1px solid var(--border-color)',
        }}>
          {(['chat', 'dashboard'] as View[]).map((view) => (
            <button
              key={view}
              onClick={() => setActiveView(view)}
              style={{
                flex: 1,
                padding: '8px 12px',
                borderRadius: '10px',
                border: 'none',
                fontSize: '12px',
                fontWeight: 600,
                fontFamily: 'var(--font-mono)',
                textTransform: 'uppercase',
                letterSpacing: '0.04em',
                cursor: 'pointer',
                transition: 'all 0.2s',
                background: activeView === view ? 'var(--bg-tertiary)' : 'transparent',
                color: activeView === view ? 'var(--accent-green)' : 'var(--text-secondary)',
              }}
            >
              {view === 'chat' ? '💬 Chat' : '📈 Metrics'}
            </button>
          ))}
        </div>

        {/* Schema Explorer (only visible in chat view) */}
        {activeView === 'chat' && (
          <SchemaExplorer schema={schema} activeTables={activeTables} />
        )}

        {/* Dashboard sidebar info */}
        {activeView === 'dashboard' && (
          <div style={{
            padding: '20px 16px',
            display: 'flex',
            flexDirection: 'column',
            gap: '12px',
            color: 'var(--text-secondary)',
            fontSize: '13px',
            lineHeight: '1.6',
          }}>
            <p style={{ fontFamily: 'var(--font-sans)' }}>
              Monitor your AI agent's query performance, success rates, and usage patterns.
            </p>
            <div style={{
              padding: '12px',
              borderRadius: '10px',
              background: 'var(--bg-secondary)',
              border: '1px solid var(--border-color)',
              fontSize: '11px',
              fontFamily: 'var(--font-mono)',
              color: 'var(--text-secondary)',
            }}>
              Data refreshes on page load. Switch back to Chat to query your database.
            </div>
          </div>
        )}
      </div>

      {/* Main area */}
      <div style={{ flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
        {activeView === 'chat' ? (
          <ChatWindow
            messages={messages}
            setMessages={setMessages}
            onAnswer={handleAnswer}
          />
        ) : (
          <MetricsDashboard />
        )}
      </div>

      {/* Approval modal */}
      {pendingApproval && (
        <ApprovalModal
          sql={pendingApproval.sql}
          reason={pendingApproval.approval_reason || ''}
          onApprove={() => handleApprove(true)}
          onReject={() => {
            setPendingApproval(null)
          }}
        />
      )}
    </div>
  )
}
