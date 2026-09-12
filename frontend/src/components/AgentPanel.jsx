import React, { useState, useRef, useEffect } from 'react'

/**
 * AgentPanel — Live execution trace UI for the Compass ReAct agent.
 *
 * Shows step-by-step agent reasoning (think → tool_call → observe → critic → synthesize)
 * with animated cards and a confirmation gate for state-mutating actions.
 */

const STEP_STYLES = {
  think: {
    bg: 'rgba(30, 58, 95, 0.35)',
    border: '#2563eb',
    icon: '🧠',
    label: 'THINKING',
    labelColor: '#60a5fa',
  },
  tool_call: {
    bg: 'rgba(74, 55, 40, 0.35)',
    border: '#d97706',
    icon: '🔧',
    label: 'TOOL CALL',
    labelColor: '#fbbf24',
  },
  observe: {
    bg: 'rgba(26, 58, 42, 0.35)',
    border: '#16a34a',
    icon: '👁️',
    label: 'RESULT',
    labelColor: '#4ade80',
  },
  confirm_request: {
    bg: 'rgba(95, 30, 30, 0.35)',
    border: '#ef4444',
    icon: '⚠️',
    label: 'CONFIRMATION REQUIRED',
    labelColor: '#f87171',
  },
  critic: {
    bg: 'rgba(58, 42, 74, 0.35)',
    border: '#9333ea',
    icon: '⚖️',
    label: 'SELF-CRITIQUE',
    labelColor: '#c084fc',
  },
  synthesize: {
    bg: 'linear-gradient(135deg, rgba(30, 58, 95, 0.25), rgba(58, 42, 74, 0.25))',
    border: '#8b5cf6',
    icon: '✨',
    label: 'SYNTHESIS',
    labelColor: '#a78bfa',
  },
  error: {
    bg: 'rgba(95, 30, 30, 0.35)',
    border: '#ef4444',
    icon: '❌',
    label: 'ERROR',
    labelColor: '#f87171',
  },
  done: {
    bg: 'rgba(26, 58, 42, 0.2)',
    border: '#16a34a',
    icon: '✅',
    label: 'COMPLETE',
    labelColor: '#4ade80',
  },
}

const SUGGESTED_GOALS = [
  "Plan my week considering all hackathon deadlines and coursework",
  "Flag any deadline conflicts this week and suggest resolutions",
  "Write a retrospective for the Compass project",
  "What are my most urgent tasks across all domains?",
  "Summarize my open tasks and suggest what to tackle first",
]

function StepCard({ step, index }) {
  const style = STEP_STYLES[step.type] || STEP_STYLES.think
  const isGradient = step.type === 'synthesize'

  return (
    <div
      style={{
        background: isGradient ? style.bg : style.bg,
        border: `1px solid ${style.border}33`,
        borderLeft: `3px solid ${style.border}`,
        borderRadius: '8px',
        padding: '12px 16px',
        marginBottom: '8px',
        animation: 'slideIn 0.3s ease-out',
      }}
    >
      <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '6px' }}>
        <span style={{ fontSize: '14px' }}>{style.icon}</span>
        <span style={{
          fontSize: '10px',
          fontWeight: '700',
          letterSpacing: '0.05em',
          color: style.labelColor,
          textTransform: 'uppercase',
          fontFamily: 'JetBrains Mono, monospace',
        }}>
          {style.label}
        </span>
        <span style={{
          fontSize: '10px',
          color: '#64748b',
          marginLeft: 'auto',
          fontFamily: 'JetBrains Mono, monospace',
        }}>
          Step {step.step} · {step.elapsed_ms}ms
        </span>
      </div>

      {step.tool && (
        <div style={{
          fontSize: '12px',
          color: '#fbbf24',
          fontFamily: 'JetBrains Mono, monospace',
          marginBottom: '4px',
        }}>
          {step.tool}({step.args ? JSON.stringify(step.args) : ''})
        </div>
      )}

      <div style={{
        fontSize: '13px',
        color: '#e2e8f0',
        lineHeight: '1.6',
        whiteSpace: 'pre-wrap',
        wordBreak: 'break-word',
      }}>
        {step.type === 'done' ? formatDoneSummary(step.content) : step.content}
      </div>
    </div>
  )
}

function formatDoneSummary(content) {
  try {
    const data = JSON.parse(content)
    return `Completed in ${data.total_steps} steps. Tools used: ${(data.tools_used || []).join(', ') || 'none'}. ${(data.pending_confirmations || []).length > 0 ? `⚠️ ${data.pending_confirmations.length} action(s) awaiting your approval.` : ''}`
  } catch {
    return content
  }
}

export default function AgentPanel() {
  const [goal, setGoal] = useState('')
  const [steps, setSteps] = useState([])
  const [isRunning, setIsRunning] = useState(false)
  const [pendingActions, setPendingActions] = useState([])
  const [currentRunId, setCurrentRunId] = useState(null)
  const [undoStatus, setUndoStatus] = useState(null)
  const [rejectFeedback, setRejectFeedback] = useState('')
  const [showRejectInput, setShowRejectInput] = useState(false)
  const [activityList, setActivityList] = useState([])
  const [critiqueStats, setCritiqueStats] = useState(null)
  const traceEndRef = useRef(null)
  const abortRef = useRef(null)

  const getApiBase = () => {
    return window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1'
      ? 'http://127.0.0.1:8000'
      : ''
  }

  const fetchActivity = async () => {
    try {
      const res = await fetch(`${getApiBase()}/api/agent/activity?limit=15`)
      if (res.ok) {
        const data = await res.json()
        setActivityList(data.activity || [])
      }
    } catch {
      // ignore
    }
  }

  const fetchCritiqueStats = async () => {
    try {
      const res = await fetch(`${getApiBase()}/api/agent/critique-stats`)
      if (res.ok) {
        const data = await res.json()
        setCritiqueStats(data)
      }
    } catch {
      // ignore
    }
  }

  useEffect(() => {
    fetchActivity()
    fetchCritiqueStats()
  }, [])

  // Auto-scroll to bottom as new steps appear
  useEffect(() => {
    if (traceEndRef.current) {
      traceEndRef.current.scrollIntoView({ behavior: 'smooth' })
    }
  }, [steps])

  const streamFromEndpoint = async (payload) => {
    setIsRunning(true)
    const controller = new AbortController()
    abortRef.current = controller

    try {
      const apiBase = getApiBase()
      const response = await fetch(`${apiBase}/api/agent/run`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
        signal: controller.signal,
      })

      if (!response.ok) {
        throw new Error(`Agent request failed: ${response.status}`)
      }

      const reader = response.body.getReader()
      const decoder = new TextDecoder()
      let buffer = ''

      while (true) {
        const { done, value } = await reader.read()
        if (done) break

        buffer += decoder.decode(value, { stream: true })
        const lines = buffer.split('\n')
        buffer = lines.pop() || ''

        for (const line of lines) {
          if (line.startsWith('data: ')) {
            try {
              const event = JSON.parse(line.slice(6))
              setSteps(prev => [...prev, event])

              if (event.run_id) {
                setCurrentRunId(event.run_id)
              }

              // Collect pending confirmations
              if (event.type === 'confirm_request') {
                setPendingActions(prev => [...prev, { tool: event.tool, args: event.args }])
              }
            } catch {
              // Skip malformed events
            }
          }
        }
      }
    } catch (err) {
      if (err.name !== 'AbortError') {
        setSteps(prev => [...prev, {
          type: 'error',
          content: `Connection error: ${err.message}`,
          step: 0,
          elapsed_ms: 0,
        }])
      }
    } finally {
      setIsRunning(false)
      abortRef.current = null
      fetchActivity()
      fetchCritiqueStats()
    }
  }

  const runAgent = async (goalText) => {
    if (!goalText.trim()) return
    setSteps([])
    setPendingActions([])
    setCurrentRunId(null)
    setUndoStatus(null)
    setShowRejectInput(false)

    await streamFromEndpoint({
      goal: goalText,
      max_steps: 8,
      enable_critic: true,
      confirmed_actions: [],
    })
  }

  const stopAgent = () => {
    if (abortRef.current) {
      abortRef.current.abort()
      setIsRunning(false)
    }
  }

  const approveActions = async () => {
    if (pendingActions.length === 0) return
    const actionsToApprove = [...pendingActions]
    setPendingActions([])
    setShowRejectInput(false)

    // Resume agent with action='approve' so it executes mutation and finishes
    await streamFromEndpoint({
      run_id: currentRunId,
      goal: goal,
      action: 'approve',
      confirmed_actions: actionsToApprove,
    })
  }

  const rejectActions = async () => {
    const feedback = rejectFeedback.trim() || 'User declined proposed change. Do not modify this task and propose an alternative plan.'
    setPendingActions([])
    setShowRejectInput(false)
    setRejectFeedback('')

    // Resume agent with action='reject' so it re-plans!
    await streamFromEndpoint({
      run_id: currentRunId,
      goal: goal,
      action: 'reject',
      feedback: feedback,
    })
  }

  const undoLastAction = async () => {
    try {
      const apiBase = getApiBase()
      const res = await fetch(`${apiBase}/api/agent/undo`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': 'Bearer dev-token',
        },
        body: JSON.stringify({ run_id: currentRunId }),
      })
      const data = await res.json()
      if (res.ok && data.status === 'ok') {
        setUndoStatus(data.message || 'Action reverted')
        setSteps(prev => [...prev, {
          type: 'observe',
          content: `↩️ UNDO: ${data.message} (${JSON.stringify(data.reverted || {})})`,
          step: prev.length + 1,
          elapsed_ms: 0,
        }])
        fetchActivity()
      } else {
        setUndoStatus(data.message || 'Nothing to undo')
      }
    } catch (err) {
      setUndoStatus(`Undo failed: ${err.message}`)
    }
  }

  const revertActivityItem = async (auditLogId) => {
    try {
      const apiBase = getApiBase()
      const res = await fetch(`${apiBase}/api/agent/undo`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': 'Bearer dev-token',
        },
        body: JSON.stringify({ audit_log_id: auditLogId }),
      })
      const data = await res.json()
      if (res.ok && data.status === 'ok') {
        setUndoStatus(data.message || 'Action reverted')
        fetchActivity()
      } else {
        setUndoStatus(data.message || 'Failed to revert action')
      }
    } catch (err) {
      setUndoStatus(`Undo failed: ${err.message}`)
    }
  }

  return (
    <div style={{
      flex: 1,
      display: 'flex',
      flexDirection: 'column',
      overflow: 'hidden',
      padding: '0',
    }}>
      <style>{`
        @keyframes slideIn {
          from { opacity: 0; transform: translateY(8px); }
          to { opacity: 1; transform: translateY(0); }
        }
        @keyframes pulse {
          0%, 100% { opacity: 1; }
          50% { opacity: 0.5; }
        }
      `}</style>

      {/* Goal Input Area */}
      <div style={{
        padding: '16px 20px',
        borderBottom: '1px solid #1e293b',
        flexShrink: 0,
      }}>
        <div style={{
          display: 'flex',
          gap: '8px',
          marginBottom: '10px',
        }}>
          <input
            id="agent-goal-input"
            type="text"
            value={goal}
            onChange={e => setGoal(e.target.value)}
            onKeyDown={e => e.key === 'Enter' && !isRunning && runAgent(goal)}
            placeholder="What should the agent work on?"
            disabled={isRunning}
            style={{
              flex: 1,
              padding: '10px 14px',
              background: '#0f172a',
              border: '1px solid #1e293b',
              borderRadius: '8px',
              color: '#e2e8f0',
              fontSize: '14px',
              outline: 'none',
              fontFamily: 'Inter, system-ui, sans-serif',
            }}
          />
          {isRunning ? (
            <button
              id="agent-stop-btn"
              onClick={stopAgent}
              style={{
                padding: '10px 18px',
                background: '#dc2626',
                border: 'none',
                borderRadius: '8px',
                color: '#fff',
                fontSize: '13px',
                fontWeight: '600',
                cursor: 'pointer',
                whiteSpace: 'nowrap',
              }}
            >
              ⏹ Stop
            </button>
          ) : (
            <button
              id="agent-run-btn"
              onClick={() => runAgent(goal)}
              disabled={!goal.trim()}
              style={{
                padding: '10px 18px',
                background: goal.trim() ? '#2563eb' : '#1e293b',
                border: 'none',
                borderRadius: '8px',
                color: goal.trim() ? '#fff' : '#64748b',
                fontSize: '13px',
                fontWeight: '600',
                cursor: goal.trim() ? 'pointer' : 'not-allowed',
                whiteSpace: 'nowrap',
              }}
            >
              🧠 Run Agent
            </button>
          )}
        </div>

        {/* Suggested goals and pre-loaded demo trigger */}
        {steps.length === 0 && (
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: '6px', alignItems: 'center' }}>
            <button
              id="agent-demo-reject-btn"
              onClick={() => {
                const demoGoal = "Detect deadline conflicts between hackathon deliverables and coursework and reschedule"
                setGoal(demoGoal)
                setRejectFeedback("Do not move OS Homework 2 deadline")
                runAgent(demoGoal)
              }}
              style={{
                padding: '5px 12px',
                background: 'linear-gradient(135deg, rgba(239, 68, 68, 0.25), rgba(217, 119, 6, 0.25))',
                border: '1px solid #ef444488',
                borderRadius: '14px',
                color: '#f87171',
                fontSize: '11px',
                fontWeight: '700',
                cursor: 'pointer',
                display: 'flex',
                alignItems: 'center',
                gap: '4px',
                transition: 'all 0.2s',
              }}
              title="Click to run the flagship Deadline Conflict scenario ready for reject & re-planning"
            >
              ⚡ Demo: Reject-Path Scenario
            </button>
            {SUGGESTED_GOALS.map((sg, i) => (
              <button
                key={i}
                onClick={() => { setGoal(sg); runAgent(sg) }}
                style={{
                  padding: '5px 10px',
                  background: '#1e293b',
                  border: '1px solid #334155',
                  borderRadius: '14px',
                  color: '#94a3b8',
                  fontSize: '11px',
                  cursor: 'pointer',
                  transition: 'all 0.2s',
                }}
                onMouseEnter={e => { e.target.style.background = '#334155'; e.target.style.color = '#e2e8f0' }}
                onMouseLeave={e => { e.target.style.background = '#1e293b'; e.target.style.color = '#94a3b8' }}
              >
                {sg}
              </button>
            ))}
          </div>
        )}
      </div>

      {/* Execution Trace */}
      <div style={{
        flex: 1,
        overflowY: 'auto',
        padding: '16px 20px',
      }}>
        {steps.length === 0 && !isRunning && (
          <div style={{
            textAlign: 'center',
            padding: '60px 20px',
            color: '#475569',
          }}>
            <div style={{ fontSize: '48px', marginBottom: '12px' }}>🧠</div>
            <div style={{ fontSize: '16px', fontWeight: '600', color: '#64748b', marginBottom: '8px' }}>
              Compass Agent
            </div>
            <div style={{ fontSize: '13px', lineHeight: '1.6', maxWidth: '420px', margin: '0 auto' }}>
              The agent autonomously plans, queries your tasks and code memory,
              detects conflicts, and proposes concrete solutions.
              State-changing actions require your approval before execution.
            </div>
          </div>
        )}

        {isRunning && steps.length === 0 && (
          <div style={{
            textAlign: 'center',
            padding: '40px',
            color: '#60a5fa',
          }}>
            <div style={{ fontSize: '20px', animation: 'pulse 1.5s ease-in-out infinite' }}>
              🧠 Agent is initializing...
            </div>
          </div>
        )}

        {steps.map((step, i) => (
          <StepCard key={i} step={step} index={i} />
        ))}

        {/* Confirmation gate UI */}
        {pendingActions.length > 0 && !isRunning && (
          <div style={{
            background: 'rgba(95, 30, 30, 0.2)',
            border: '1px solid #ef4444',
            borderRadius: '8px',
            padding: '16px',
            marginTop: '8px',
          }}>
            <div style={{ fontSize: '14px', fontWeight: '600', color: '#f87171', marginBottom: '8px' }}>
              ⚠️ {pendingActions.length} action(s) need your approval
            </div>
            <div style={{ fontSize: '12px', color: '#e2e8f0', marginBottom: '12px' }}>
              The agent wants to modify your data. Review and approve or reject:
            </div>
            {pendingActions.map((action, i) => (
              <div key={i} style={{
                background: '#1e293b',
                borderRadius: '6px',
                padding: '8px 12px',
                marginBottom: '6px',
                fontFamily: 'JetBrains Mono, monospace',
                fontSize: '12px',
                color: '#fbbf24',
              }}>
                {action.tool}({JSON.stringify(action.args)})
              </div>
            ))}
            <div style={{ marginTop: '10px' }}>
              <input
                id="agent-reject-input"
                type="text"
                value={rejectFeedback}
                onChange={e => setRejectFeedback(e.target.value)}
                placeholder="Optional feedback for re-planning (e.g., 'don't reschedule this task')..."
                style={{
                  width: '100%',
                  padding: '8px 12px',
                  background: '#0f172a',
                  border: '1px solid #334155',
                  borderRadius: '6px',
                  color: '#e2e8f0',
                  fontSize: '12px',
                  marginBottom: '10px',
                  outline: 'none',
                  boxSizing: 'border-box',
                }}
              />
            </div>
            <div style={{ display: 'flex', gap: '8px', marginTop: '4px' }}>
              <button
                id="agent-approve-btn"
                onClick={approveActions}
                style={{
                  padding: '8px 16px',
                  background: '#16a34a',
                  border: 'none',
                  borderRadius: '6px',
                  color: '#fff',
                  fontSize: '13px',
                  fontWeight: '600',
                  cursor: 'pointer',
                }}
              >
                ✅ Approve & Execute
              </button>
              <button
                id="agent-reject-btn"
                onClick={rejectActions}
                style={{
                  padding: '8px 16px',
                  background: '#dc2626',
                  border: 'none',
                  borderRadius: '6px',
                  color: '#fff',
                  fontSize: '13px',
                  fontWeight: '600',
                  cursor: 'pointer',
                }}
              >
                ❌ Reject & Re-plan
              </button>
            </div>
          </div>
        )}

        {/* Global Undo Button when steps or mutations exist */}
        {steps.some(s => s.type === 'observe' && (s.tool === 'add_task' || s.tool === 'edit_task' || s.tool === 'update_task_status' || s.tool === 'delete_task')) && (
          <div style={{ marginTop: '12px', marginBottom: '8px' }}>
            <button
              id="agent-undo-btn"
              onClick={undoLastAction}
              style={{
                padding: '6px 14px',
                background: '#475569',
                border: '1px solid #64748b',
                borderRadius: '6px',
                color: '#e2e8f0',
                fontSize: '12px',
                cursor: 'pointer',
                display: 'flex',
                alignItems: 'center',
                gap: '6px',
              }}
            >
              ↩️ Undo Last Agent Mutation
            </button>
            {undoStatus && (
              <span style={{ fontSize: '11px', color: '#94a3b8', marginLeft: '10px' }}>
                {undoStatus}
              </span>
            )}
          </div>
        )}

        {isRunning && (
          <div style={{
            display: 'flex',
            alignItems: 'center',
            gap: '8px',
            padding: '8px 0',
            color: '#60a5fa',
            fontSize: '12px',
          }}>
            <span style={{ animation: 'pulse 1s ease-in-out infinite' }}>●</span>
            Agent is reasoning...
          </div>
        )}

        {/* Visible Agent Activity Feed (backed by agent_audit_log with per-item undo) */}
        <div id="agent-activity-feed" style={{
          marginTop: '24px',
          borderTop: '1px solid #1e293b',
          paddingTop: '16px',
        }}>
          <div style={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            marginBottom: '10px',
          }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
              <span style={{
                fontSize: '12px',
                fontWeight: '700',
                letterSpacing: '0.05em',
                color: '#94a3b8',
                textTransform: 'uppercase',
              }}>
                📋 Agent Activity Audit Log ({activityList.length})
              </span>
              {critiqueStats && (
                <span style={{
                  fontSize: '11px',
                  color: '#c084fc',
                  background: 'rgba(147, 51, 234, 0.12)',
                  padding: '2px 8px',
                  borderRadius: '10px',
                  border: '1px solid #9333ea33',
                }}>
                  ⚖️ Critique flag rate: {critiqueStats.critique_effectiveness_rate}% ({critiqueStats.critique_issues_flagged}/{critiqueStats.runs_with_critique})
                </span>
              )}
            </div>
            <button
              onClick={() => { fetchActivity(); fetchCritiqueStats() }}
              style={{
                fontSize: '11px',
                background: 'transparent',
                border: 'none',
                color: '#60a5fa',
                cursor: 'pointer',
              }}
            >
              ↻ Refresh
            </button>
          </div>

          {activityList.length === 0 ? (
            <div style={{ fontSize: '12px', color: '#64748b', fontStyle: 'italic', padding: '8px 0' }}>
              No state mutations executed by the agent yet.
            </div>
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
              {activityList.map((item) => (
                <div
                  key={item.id}
                  className="agent-activity-item"
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'space-between',
                    padding: '8px 12px',
                    background: item.is_reverted ? 'rgba(30, 41, 59, 0.2)' : 'rgba(30, 41, 59, 0.5)',
                    border: `1px solid ${item.is_reverted ? '#334155' : '#1e293b'}`,
                    borderRadius: '6px',
                    fontSize: '12px',
                  }}
                >
                  <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                    <span style={{
                      padding: '2px 6px',
                      background: '#0f172a',
                      borderRadius: '4px',
                      fontSize: '10px',
                      fontWeight: '700',
                      color: '#fbbf24',
                      fontFamily: 'monospace',
                    }}>
                      {item.tool}
                    </span>
                    <span style={{ color: '#e2e8f0' }}>
                      {item.affected_table} #{item.affected_id}
                    </span>
                    <span style={{ fontSize: '10px', color: '#64748b' }}>
                      {item.created_at ? item.created_at.slice(11, 19) : ''}
                    </span>
                    <span style={{
                      fontSize: '9px',
                      padding: '1px 5px',
                      borderRadius: '4px',
                      fontWeight: '700',
                      background: item.is_reverted ? 'rgba(239, 68, 68, 0.2)' : 'rgba(34, 197, 94, 0.2)',
                      color: item.is_reverted ? '#f87171' : '#4ade80',
                      border: `1px solid ${item.is_reverted ? '#ef444444' : '#22c55e44'}`,
                    }}>
                      {item.is_reverted ? 'REVERTED' : 'ACTIVE'}
                    </span>
                  </div>

                  {!item.is_reverted && (
                    <button
                      className="agent-revert-btn"
                      onClick={() => revertActivityItem(item.id)}
                      style={{
                        padding: '3px 8px',
                        background: '#334155',
                        border: '1px solid #475569',
                        borderRadius: '4px',
                        color: '#f87171',
                        fontSize: '10px',
                        fontWeight: '600',
                        cursor: 'pointer',
                      }}
                      title={`Revert action #${item.id}`}
                    >
                      ↩️ Revert
                    </button>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>

        <div ref={traceEndRef} />
      </div>
    </div>
  )
}
