/**
 * MetricsDashboard — Analytics dashboard showing query performance metrics.
 *
 * Displays:
 * - Summary cards (total queries, success rate, avg latency, avg retries)
 * - Daily queries line chart (last 7 days)
 * - Top queried tables bar chart
 *
 * Fetches data from GET /api/analytics.
 */

import { useState, useEffect } from 'react'
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip,
  ResponsiveContainer, LineChart, Line, Area, AreaChart,
} from 'recharts'
import { getAnalytics, type AnalyticsData } from '../api'

export default function MetricsDashboard() {
  const [data, setData] = useState<AnalyticsData | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    getAnalytics()
      .then(setData)
      .catch((err) => setError(err.message || 'Failed to load analytics'))
      .finally(() => setLoading(false))
  }, [])

  if (loading) {
    return (
      <div style={{
        display: 'flex', alignItems: 'center', justifyContent: 'center',
        height: '100%', color: 'var(--text-secondary)', fontFamily: 'var(--font-mono)',
      }}>
        Loading analytics...
      </div>
    )
  }

  if (error || !data) {
    return (
      <div style={{
        display: 'flex', alignItems: 'center', justifyContent: 'center',
        height: '100%', color: 'var(--accent-red)', fontFamily: 'var(--font-mono)',
        fontSize: '14px',
      }}>
        {error || 'No data available'}
      </div>
    )
  }

  const cards = [
    { label: 'Total Queries', value: data.total_queries.toLocaleString(), icon: '📊', color: 'var(--accent-green)' },
    { label: 'Success Rate', value: `${data.success_rate}%`, icon: '✅', color: data.success_rate >= 90 ? 'var(--accent-green)' : 'var(--accent-yellow)' },
    { label: 'Avg Latency', value: `${data.avg_latency_ms}ms`, icon: '⚡', color: data.avg_latency_ms < 5000 ? 'var(--accent-cyan)' : 'var(--accent-yellow)' },
    { label: 'Avg Retries', value: data.avg_retry_count.toFixed(2), icon: '🔧', color: data.avg_retry_count < 0.5 ? 'var(--accent-green)' : 'var(--accent-yellow)' },
  ]

  return (
    <div style={{
      height: '100%', overflowY: 'auto', padding: '32px',
      display: 'flex', flexDirection: 'column', gap: '28px',
    }}>
      {/* Header */}
      <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
        <span style={{ fontSize: '24px' }}>📈</span>
        <div>
          <h2 style={{
            fontSize: '20px', fontWeight: 700,
            color: 'var(--text-primary)', margin: 0,
            fontFamily: 'var(--font-sans)',
          }}>
            Agent Performance
          </h2>
          <p style={{
            fontSize: '13px', color: 'var(--text-secondary)',
            margin: '4px 0 0 0', fontFamily: 'var(--font-mono)',
          }}>
            Real-time query analytics
          </p>
        </div>
      </div>

      {/* Summary Cards */}
      <div style={{
        display: 'grid',
        gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))',
        gap: '16px',
      }}>
        {cards.map((card) => (
          <div
            key={card.label}
            style={{
              background: 'var(--bg-secondary)',
              border: '1px solid var(--border-color)',
              borderRadius: '16px',
              padding: '20px 24px',
              display: 'flex',
              flexDirection: 'column',
              gap: '8px',
              transition: 'border-color 0.2s, transform 0.2s',
              cursor: 'default',
            }}
            onMouseEnter={(e) => {
              e.currentTarget.style.borderColor = card.color
              e.currentTarget.style.transform = 'translateY(-2px)'
            }}
            onMouseLeave={(e) => {
              e.currentTarget.style.borderColor = 'var(--border-color)'
              e.currentTarget.style.transform = 'translateY(0)'
            }}
          >
            <div style={{
              display: 'flex', alignItems: 'center', gap: '8px',
            }}>
              <span style={{ fontSize: '16px' }}>{card.icon}</span>
              <span style={{
                fontSize: '11px', fontWeight: 600, textTransform: 'uppercase',
                letterSpacing: '0.06em', color: 'var(--text-secondary)',
                fontFamily: 'var(--font-mono)',
              }}>
                {card.label}
              </span>
            </div>
            <span style={{
              fontSize: '28px', fontWeight: 700,
              color: card.color, fontFamily: 'var(--font-mono)',
              letterSpacing: '-0.02em',
            }}>
              {card.value}
            </span>
          </div>
        ))}
      </div>

      {/* Charts Row */}
      <div style={{
        display: 'grid',
        gridTemplateColumns: data.daily_queries.length > 0 ? '1fr 1fr' : '1fr',
        gap: '16px',
      }}>
        {/* Daily Queries Chart */}
        {data.daily_queries.length > 0 && (
          <div style={{
            background: 'var(--bg-secondary)',
            border: '1px solid var(--border-color)',
            borderRadius: '16px',
            padding: '24px',
          }}>
            <h3 style={{
              fontSize: '13px', fontWeight: 600, marginBottom: '20px',
              color: 'var(--text-primary)', fontFamily: 'var(--font-sans)',
              display: 'flex', alignItems: 'center', gap: '8px',
            }}>
              <span style={{
                display: 'inline-block', width: '8px', height: '8px',
                borderRadius: '50%', background: 'var(--accent-cyan)',
              }} />
              Queries Over Time
            </h3>
            <div style={{ width: '100%', height: 200 }}>
              <ResponsiveContainer width="100%" height="100%">
                <AreaChart data={data.daily_queries}>
                  <defs>
                    <linearGradient id="colorQueries" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="5%" stopColor="var(--accent-cyan)" stopOpacity={0.3} />
                      <stop offset="95%" stopColor="var(--accent-cyan)" stopOpacity={0} />
                    </linearGradient>
                  </defs>
                  <CartesianGrid strokeDasharray="3 3" stroke="var(--border-color)" vertical={false} />
                  <XAxis
                    dataKey="date"
                    stroke="var(--text-secondary)"
                    fontSize={11}
                    tickLine={false}
                    axisLine={false}
                    tickFormatter={(v: string) => v.slice(5)} // Show MM-DD
                  />
                  <YAxis
                    stroke="var(--text-secondary)"
                    fontSize={11}
                    tickLine={false}
                    axisLine={false}
                  />
                  <Tooltip
                    contentStyle={{
                      background: 'var(--bg-secondary)',
                      border: '1px solid var(--border-color)',
                      borderRadius: '8px',
                      fontSize: '12px',
                    }}
                  />
                  <Area
                    type="monotone"
                    dataKey="count"
                    stroke="var(--accent-cyan)"
                    strokeWidth={2}
                    fill="url(#colorQueries)"
                  />
                </AreaChart>
              </ResponsiveContainer>
            </div>
          </div>
        )}

        {/* Top Tables Chart */}
        {data.top_tables.length > 0 && (
          <div style={{
            background: 'var(--bg-secondary)',
            border: '1px solid var(--border-color)',
            borderRadius: '16px',
            padding: '24px',
          }}>
            <h3 style={{
              fontSize: '13px', fontWeight: 600, marginBottom: '20px',
              color: 'var(--text-primary)', fontFamily: 'var(--font-sans)',
              display: 'flex', alignItems: 'center', gap: '8px',
            }}>
              <span style={{
                display: 'inline-block', width: '8px', height: '8px',
                borderRadius: '50%', background: 'var(--accent-green)',
              }} />
              Most Queried Tables
            </h3>
            <div style={{ width: '100%', height: 200 }}>
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={data.top_tables} layout="vertical">
                  <CartesianGrid strokeDasharray="3 3" stroke="var(--border-color)" horizontal={false} />
                  <XAxis
                    type="number"
                    stroke="var(--text-secondary)"
                    fontSize={11}
                    tickLine={false}
                    axisLine={false}
                  />
                  <YAxis
                    dataKey="table"
                    type="category"
                    stroke="var(--text-secondary)"
                    fontSize={11}
                    tickLine={false}
                    axisLine={false}
                    width={120}
                  />
                  <Tooltip
                    contentStyle={{
                      background: 'var(--bg-secondary)',
                      border: '1px solid var(--border-color)',
                      borderRadius: '8px',
                      fontSize: '12px',
                    }}
                  />
                  <Bar
                    dataKey="count"
                    fill="var(--accent-green)"
                    radius={[0, 4, 4, 0]}
                    barSize={20}
                  />
                </BarChart>
              </ResponsiveContainer>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
