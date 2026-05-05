/**
 * InsightPanel — Displays AI-generated natural language insights
 * below the results table. Styled as a subtle callout card with
 * a lightbulb icon and glassmorphism effect.
 */

interface Props {
  insight: string
  isDecomposed?: boolean
  subQueryCount?: number
  retryCount?: number
}

export default function InsightPanel({ insight, isDecomposed, subQueryCount, retryCount }: Props) {
  if (!insight) return null

  return (
    <div style={{
      background: 'linear-gradient(135deg, rgba(0, 255, 136, 0.06) 0%, rgba(0, 188, 212, 0.04) 100%)',
      border: '1px solid rgba(0, 255, 136, 0.15)',
      borderRadius: '16px',
      padding: '20px 24px',
      position: 'relative',
      overflow: 'hidden',
    }}>
      {/* Subtle glow effect */}
      <div style={{
        position: 'absolute',
        top: '-20px',
        left: '-20px',
        width: '80px',
        height: '80px',
        background: 'radial-gradient(circle, rgba(0, 255, 136, 0.1) 0%, transparent 70%)',
        pointerEvents: 'none',
      }} />

      {/* Header */}
      <div style={{
        display: 'flex',
        alignItems: 'center',
        gap: '10px',
        marginBottom: '12px',
      }}>
        <span style={{ fontSize: '18px' }}>💡</span>
        <span style={{
          fontSize: '12px',
          fontWeight: 700,
          textTransform: 'uppercase',
          letterSpacing: '0.08em',
          color: 'var(--accent-green)',
          fontFamily: 'var(--font-mono)',
        }}>
          AI Insight
        </span>

        {/* Badges */}
        <div style={{ display: 'flex', gap: '6px', marginLeft: 'auto' }}>
          {isDecomposed && (
            <span style={{
              fontSize: '11px',
              padding: '2px 8px',
              borderRadius: '6px',
              background: 'rgba(0, 188, 212, 0.15)',
              color: 'var(--accent-cyan)',
              fontFamily: 'var(--font-mono)',
              fontWeight: 600,
            }}>
              🔀 {subQueryCount} sub-queries
            </span>
          )}
          {(retryCount ?? 0) > 0 && (
            <span style={{
              fontSize: '11px',
              padding: '2px 8px',
              borderRadius: '6px',
              background: 'rgba(255, 184, 108, 0.15)',
              color: 'var(--accent-yellow)',
              fontFamily: 'var(--font-mono)',
              fontWeight: 600,
            }}>
              🔧 {retryCount} {retryCount === 1 ? 'retry' : 'retries'}
            </span>
          )}
        </div>
      </div>

      {/* Insight text */}
      <p style={{
        fontSize: '14px',
        lineHeight: '1.7',
        color: 'var(--text-primary)',
        margin: 0,
        fontFamily: 'var(--font-sans)',
        opacity: 0.9,
      }}>
        {insight}
      </p>
    </div>
  )
}
