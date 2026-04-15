import { useState, useRef, useEffect } from 'react'
import { postQueryStream, type QueryResponse } from '../api'
import SqlDisplay from './SqlDisplay'
import ResultsTable from './ResultsTable'
import ChartDisplay from './ChartDisplay'
import SkeletonLoader from './SkeletonLoader'
import type { Message } from '../App'

interface Props {
  messages: Message[]
  setMessages: React.Dispatch<React.SetStateAction<Message[]>>
  onAnswer: (response: QueryResponse) => void
}

export default function ChatWindow({ messages, setMessages, onAnswer }: Props) {
  const [question, setQuestion] = useState('')
  const [loading, setLoading] = useState(false)
  const bottomRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  const handleSubmit = async () => {
    const q = question.trim()
    if (!q || loading) return

    // Extract history for multi-turn context (last 3 turns)
    const history: { question: string, sql: string }[] = []
    for (let i = 0; i < messages.length; i++) {
      if (messages[i].type === 'question' && messages[i + 1]?.type === 'answer') {
        const qText = messages[i].content as string
        const ans = messages[i + 1].content as QueryResponse
        history.push({ question: qText, sql: ans.sql })
      }
    }
    const slicedHistory = history.slice(-3)

    // Add user question
    const questionMsg: Message = {
      id: crypto.randomUUID(),
      type: 'question',
      content: q,
      timestamp: new Date(),
    }
    
    // Add a placeholder for the streaming answer
    const answerId = crypto.randomUUID()
    const placeholderAnswer: Message = {
      id: answerId,
      type: 'answer',
      content: {
        sql: '',
        results: [],
        tables_used: [],
        requires_approval: false,
        latency_ms: 0,
        timing: { retrieval_ms: 0, llm_ms: 0, execution_ms: 0 }
      } as QueryResponse,
      timestamp: new Date(),
    }

    setMessages((prev) => [...prev, questionMsg, placeholderAnswer])
    setQuestion('')
    setLoading(true)

    try {
      const stream = await postQueryStream(q, slicedHistory)
      const reader = stream.getReader()
      const decoder = new TextDecoder()
      let streamBuffer = ''

      while (true) {
        const { done, value } = await reader.read()
        if (done) break
        
        streamBuffer += decoder.decode(value, { stream: true })
        const lines = streamBuffer.split('\n\n')
        streamBuffer = lines.pop() || ''

        for (const line of lines) {
          if (!line.startsWith('data: ')) continue
          
          try {
            const payload = JSON.parse(line.substring(6))
            const { event, data } = payload

            if (event === 'sql_chunk') {
              setMessages((prev) => prev.map(m => 
                m.id === answerId 
                  ? { ...m, content: { ...m.content as QueryResponse, sql: (m.content as QueryResponse).sql + data } } 
                  : m
              ))
            } else if (event === 'sql_fix') {
              // Self-healing: replace broken SQL with the corrected version
              setMessages((prev) => prev.map(m => 
                m.id === answerId 
                  ? { ...m, content: { ...m.content as QueryResponse, sql: data } } 
                  : m
              ))
            } else if (event === 'final_result') {
              setMessages((prev) => prev.map(m => m.id === answerId ? { ...m, content: data } : m))
              onAnswer(data) // Trigger side-effects (modal, sidebar)
            } else if (event === 'error') {
              throw new Error(data)
            }
          } catch (e) {
            console.error('Error parsing SSE chunk:', e)
          }
        }
      }
    } catch (err: unknown) {
      const errMsg = err instanceof Error ? err.message : String(err)
      setMessages((prev) => {
        // Remove the placeholder if it's empty, otherwise keep it and add an error
        const filtered = prev.filter(m => m.id !== answerId || (m.content as QueryResponse).sql !== '')
        return [
          ...filtered,
          { id: crypto.randomUUID(), type: 'error', content: errMsg, timestamp: new Date() },
        ]
      })
    } finally {
      setLoading(false)
    }
  }

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSubmit()
    }
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
      {/* Message history */}
      <div style={{ 
        flex: 1, 
        overflowY: 'auto', 
        padding: '24px', 
        display: 'flex', 
        flexDirection: 'column', 
        gap: '24px' 
      }}>
        {messages.map((msg) => (
          <div
            key={msg.id}
            style={{
              alignSelf: msg.type === 'question' ? 'flex-end' : 'flex-start',
              width: 'fit-content',
              maxWidth: '95%',
              display: 'flex',
              flexDirection: 'column',
              gap: '8px',
            }}
          >
            {msg.type === 'question' ? (
              <div style={{
                background: 'var(--bg-secondary)',
                padding: '12px 16px',
                borderRadius: '16px 16px 2px 16px',
                color: 'var(--text-primary)',
                border: '1px solid var(--border-color)',
                fontSize: '15px',
                lineHeight: '1.5',
              }}>
                {msg.content as string}
              </div>
            ) : msg.type === 'error' ? (
              <div style={{
                background: 'rgba(239, 68, 68, 0.1)',
                padding: '12px 16px',
                borderRadius: '16px 16px 16px 2px',
                color: '#ef4444',
                border: '1px solid rgba(239, 68, 68, 0.2)',
                fontSize: '14px',
                fontFamily: 'var(--font-mono)',
              }}>
                {msg.content as string}
              </div>
            ) : (
              <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
                {(msg.content as QueryResponse).sql === '' ? (
                  <SkeletonLoader />
                ) : (
                  <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
                    <SqlDisplay 
                      sql={(msg.content as QueryResponse).sql} 
                      timing={(msg.content as QueryResponse).timing}
                      latencyMs={(msg.content as QueryResponse).latency_ms}
                    />
                    
                    {(msg.content as QueryResponse).visualization && 
                     (msg.content as QueryResponse).visualization?.type !== 'none' && (
                      <ChartDisplay 
                        {...(msg.content as QueryResponse).visualization!}
                        data={(msg.content as QueryResponse).results}
                      />
                    )}

                    {(msg.content as QueryResponse).results.length > 0 && (
                      <ResultsTable results={(msg.content as QueryResponse).results} />
                    )}
                  </div>
                )}
              </div>
            )}
            <div style={{
              fontSize: '11px',
              color: 'var(--text-secondary)',
              alignSelf: msg.type === 'question' ? 'flex-end' : 'flex-start',
              fontFamily: 'var(--font-mono)',
              opacity: 0.5,
            }}>
              {msg.timestamp.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
            </div>
          </div>
        ))}
        <div ref={bottomRef} />
      </div>

      {/* Input area */}
      <div style={{ 
        padding: '24px', 
        borderTop: '1px solid var(--border-color)',
        background: 'var(--bg-primary)',
      }}>
        <div style={{ 
          position: 'relative',
          maxWidth: '1200px',
          margin: '0 auto',
        }}>
          <textarea
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="Ask a question about your data... (Enter to send, Shift+Enter for newline)"
            disabled={loading}
            style={{
              width: '100%',
              padding: '16px 64px 16px 20px',
              background: 'var(--bg-secondary)',
              border: '1px solid var(--border-color)',
              borderRadius: '16px',
              color: 'var(--text-primary)',
              fontSize: '15px',
              fontFamily: 'inherit',
              resize: 'none',
              height: '56px',
              maxHeight: '200px',
              outline: 'none',
              transition: 'border-color 0.2s, box-shadow 0.2s',
            }}
          />
          <button
            onClick={handleSubmit}
            disabled={loading || !question.trim()}
            style={{
              position: 'absolute',
              right: '12px',
              top: '50%',
              transform: 'translateY(-50%)',
              width: '36px',
              height: '36px',
              borderRadius: '12px',
              background: loading ? 'transparent' : 'var(--accent-green)',
              border: 'none',
              color: '#000',
              display: 'flex',
              alignSelf: 'center',
              justifyContent: 'center',
              cursor: loading ? 'default' : 'pointer',
              transition: 'all 0.2s',
              opacity: question.trim() || loading ? 1 : 0.5,
            }}
          >
            {loading ? (
              <div className="spinner" style={{ width: '20px', height: '20px' }} />
            ) : (
              <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                <path d="m5 12 7-7 7 7M12 19V5"/>
              </svg>
            )}
          </button>
        </div>
      </div>
    </div>
  )
}
