import { useState } from 'react'
import { Prism as SyntaxHighlighter } from 'react-syntax-highlighter'
import { vscDarkPlus } from 'react-syntax-highlighter/dist/esm/styles/prism'

interface Props {
  sql: string
  latencyMs: number
  requiresApproval?: boolean
  approvalReason?: string
  timing?: Record<string, number>
}

export default function SqlDisplay({ sql, latencyMs, requiresApproval, approvalReason, timing }: Props) {
  const [copied, setCopied] = useState(false)
  const [showTiming, setShowTiming] = useState(false)

  const handleCopy = () => {
    navigator.clipboard.writeText(sql).then(() => {
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    })
  }

  return (
    <div style={{
      background: 'var(--bg-secondary)',
      border: `1px solid ${requiresApproval ? 'var(--accent-yellow)' : 'var(--border-color)'}`,
      borderRadius: '8px',
      overflow: 'hidden',
    }}>
      {/* Header */}
      <div style={{
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        padding: '8px 12px',
        background: 'var(--bg-tertiary)',
        borderBottom: '1px solid var(--border-color)',
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
          <span style={{
            fontFamily: 'var(--font-mono)',
            fontSize: '11px',
            color: 'var(--accent-green)',
            textTransform: 'uppercase',
            letterSpacing: '0.08em',
          }}>
            SQL
          </span>
          {requiresApproval && (
            <span style={{
              background: 'rgba(255,184,108,0.15)',
              color: 'var(--accent-yellow)',
              border: '1px solid var(--accent-yellow)',
              borderRadius: '4px',
              padding: '1px 6px',
              fontSize: '10px',
              fontFamily: 'var(--font-mono)',
            }}>
              ⚠ APPROVAL REQUIRED
            </span>
          )}
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
          <div 
            onMouseEnter={() => setShowTiming(true)}
            onMouseLeave={() => setShowTiming(false)}
            style={{ position: 'relative', cursor: 'help' }}
          >
            <span style={{
              fontFamily: 'var(--font-mono)',
              fontSize: '11px',
              color: 'var(--text-secondary)',
              borderBottom: '1px dotted var(--text-secondary)',
            }}>
              {latencyMs}ms
            </span>
            {showTiming && timing && (
              <div style={{
                position: 'absolute',
                top: '100%',
                right: 0,
                marginTop: '8px',
                background: 'var(--bg-tertiary)',
                border: '1px solid var(--border-color)',
                borderRadius: '6px',
                padding: '8px',
                zIndex: 100,
                width: '180px',
                boxShadow: '0 4px 12px rgba(0,0,0,0.3)',
              }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '10px', color: 'var(--text-secondary)', marginBottom: '4px' }}>
                  <span>Retrieval:</span>
                  <span style={{ color: 'var(--accent-cyan)' }}>{timing.retrieval_ms}ms</span>
                </div>
                <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '10px', color: 'var(--text-secondary)', marginBottom: '4px' }}>
                  <span>Generation:</span>
                  <span style={{ color: 'var(--accent-yellow)' }}>{timing.llm_ms}ms</span>
                </div>
                <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '10px', color: 'var(--text-secondary)' }}>
                  <span>Execution:</span>
                  <span style={{ color: 'var(--accent-green)' }}>{timing.execution_ms}ms</span>
                </div>
              </div>
            )}
          </div>
          <button
            onClick={handleCopy}
            style={{
              background: 'transparent',
              border: '1px solid var(--border-color)',
              borderRadius: '4px',
              padding: '2px 8px',
              fontSize: '11px',
              color: copied ? 'var(--accent-green)' : 'var(--text-secondary)',
              fontFamily: 'var(--font-mono)',
              transition: 'all 0.15s',
            }}
          >
            {copied ? '✓ copied' : 'copy'}
          </button>
        </div>
      </div>

      {/* SQL code */}
      <div style={{ fontSize: '12px', lineHeight: 1.6 }}>
        <SyntaxHighlighter
          language="sql"
          style={vscDarkPlus}
          customStyle={{
            margin: 0,
            padding: '12px 16px',
            background: 'var(--bg-secondary)',
            fontSize: '12px',
          }}
        >
          {sql}
        </SyntaxHighlighter>
      </div>

      {/* Approval reason */}
      {requiresApproval && approvalReason && (
        <div style={{
          padding: '8px 12px',
          borderTop: '1px solid var(--border-color)',
          fontFamily: 'var(--font-mono)',
          fontSize: '11px',
          color: 'var(--accent-yellow)',
          background: 'rgba(255,184,108,0.05)',
        }}>
          Reason: {approvalReason}
        </div>
      )}
    </div>
  )
}
