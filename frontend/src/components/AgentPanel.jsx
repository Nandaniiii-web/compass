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

function ReplanDiffCard({ diff }) {
  if (!diff) return null
  return (
    <div style={{
      margin: '10px 0 8px',
      background: 'rgba(15, 23, 42, 0.75)',
      border: '1px solid #334155',
      borderRadius: '6px',
      padding: '10px 12px',
      fontSize: '12px',
      fontFamily: 'JetBrains Mono, monospace',
    }}>
      <div style={{ color: '#94a3b8', fontWeight: '700', marginBottom: '6px', fontSize: '11px', letterSpacing: '0.05em' }}>
        🔄 RE-PLAN DIFF (HUMAN IN THE LOOP)
      </div>
      <div style={{ color: '#f87171', textDecoration: 'line-through', marginBottom: '4px' }}>
        - DECLINED: {diff.declined_action?.tool}({JSON.stringify(diff.declined_action?.args || {})})
      </div>
      <div style={{ color: '#fbbf24', marginBottom: '4px' }}>
        ~ FEEDBACK: "{diff.feedback}"
      </div>
      <div style={{ color: '#4ade80' }}>
        + RE-PLANNING: Finding non-conflicting alternative without state alteration
      </div>
    </div>
  )
}

function ReportCard({ reportCard }) {
  if (!reportCard) return null
  return (
    <div id="agent-report-card" style={{
      marginTop: '12px',
      background: 'linear-gradient(135deg, rgba(15, 23, 42, 0.95), rgba(30, 41, 59, 0.95))',
      border: '1px solid #3b82f6',
      borderRadius: '10px',
      padding: '14px 16px',
      boxShadow: '0 4px 20px rgba(0,0,0,0.4)',
    }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '12px' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
          <span style={{ fontSize: '18px' }}>📊</span>
          <span style={{ fontWeight: '700', fontSize: '13px', color: '#60a5fa', letterSpacing: '0.05em' }}>
            AGENT RUN REPORT CARD
          </span>
        </div>
        <span style={{
          fontSize: '10px',
          fontWeight: '700',
          padding: '2px 8px',
          borderRadius: '12px',
          background: reportCard.abstained ? 'rgba(245, 158, 11, 0.2)' : 'rgba(34, 197, 94, 0.2)',
          color: reportCard.abstained ? '#fbbf24' : '#4ade80',
          border: `1px solid ${reportCard.abstained ? '#f59e0b44' : '#22c55e44'}`,
        }}>
          {reportCard.abstained ? 'EPISTEMIC ABSTENTION' : 'COMPLETED'}
        </span>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: '8px', marginBottom: '12px' }}>
        <div style={{ background: '#0f172a', padding: '8px 10px', borderRadius: '6px', border: '1px solid #1e293b' }}>
          <div style={{ fontSize: '10px', color: '#64748b' }}>TOTAL TIME</div>
          <div style={{ fontSize: '13px', fontWeight: '700', color: '#e2e8f0', fontFamily: 'JetBrains Mono, monospace' }}>
            {reportCard.elapsed_ms}ms
          </div>
        </div>
        <div style={{ background: '#0f172a', padding: '8px 10px', borderRadius: '6px', border: '1px solid #1e293b' }}>
          <div style={{ fontSize: '10px', color: '#64748b' }}>STEPS</div>
          <div style={{ fontSize: '13px', fontWeight: '700', color: '#e2e8f0', fontFamily: 'JetBrains Mono, monospace' }}>
            {reportCard.total_steps}
          </div>
        </div>
        <div style={{ background: '#0f172a', padding: '8px 10px', borderRadius: '6px', border: '1px solid #1e293b' }}>
          <div style={{ fontSize: '10px', color: '#64748b' }}>CRITIQUE</div>
          <div style={{ fontSize: '13px', fontWeight: '700', color: '#c084fc', fontFamily: 'JetBrains Mono, monospace' }}>
            {reportCard.critique_rounds || 0} round(s)
          </div>
        </div>
        <div style={{ background: '#0f172a', padding: '8px 10px', borderRadius: '6px', border: '1px solid #1e293b' }}>
          <div style={{ fontSize: '10px', color: '#64748b' }}>TOTAL COST</div>
          <div style={{ fontSize: '13px', fontWeight: '700', color: '#10b981', fontFamily: 'JetBrains Mono, monospace' }}>
            ${(reportCard.total_cost_usd || 0).toFixed(5)}
          </div>
        </div>
      </div>

      {reportCard.tier_breakdown && (
        <div style={{ fontSize: '11px', color: '#94a3b8', background: '#0f172a', padding: '8px 10px', borderRadius: '6px', border: '1px solid #1e293b' }}>
          <div style={{ fontWeight: '600', marginBottom: '4px', color: '#cbd5e1' }}>Model Tier Attribution:</div>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: '12px', fontFamily: 'JetBrains Mono, monospace', fontSize: '10px' }}>
            {Object.entries(reportCard.tier_breakdown).map(([tier, cost]) => (
              <span key={tier} style={{ color: cost > 0 ? '#60a5fa' : '#64748b' }}>
                • {tier}: <strong style={{ color: cost > 0 ? '#34d399' : '#94a3b8' }}>${cost.toFixed(5)}</strong>
              </span>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}

function StepCard({ step, index }) {
  const style = STEP_STYLES[step.type] || STEP_STYLES.think
  const isGradient = step.type === 'synthesize'
  const isAbstained = step.metadata?.abstained || (typeof step.content === 'string' && step.content.includes('[ABSTAIN]'))
  const replanDiff = step.metadata?.replan_diff
  let reportCard = step.metadata?.report_card
  if (!reportCard && step.type === 'done') {
    try {
      const parsed = JSON.parse(step.content)
      reportCard = parsed.report_card
    } catch {}
  }

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
      <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '6px', flexWrap: 'wrap' }}>
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

        {/* Model Tier Attribution */}
        {step.model_tier && (
          <span style={{
            fontSize: '10px',
            color: '#94a3b8',
            background: 'rgba(30, 41, 59, 0.8)',
            padding: '2px 8px',
            borderRadius: '10px',
            border: '1px solid #334155',
            fontFamily: 'JetBrains Mono, monospace',
          }}>
            {step.model_tier}
          </span>
        )}

        {/* Live USD Cost Badge */}
        {step.step_cost_usd !== undefined && step.step_cost_usd !== null && (
          <span style={{
            fontSize: '10px',
            fontWeight: '600',
            color: step.step_cost_usd > 0 ? '#34d399' : '#64748b',
            background: step.step_cost_usd > 0 ? 'rgba(16, 185, 129, 0.12)' : 'rgba(51, 65, 85, 0.3)',
            padding: '2px 6px',
            borderRadius: '10px',
            border: `1px solid ${step.step_cost_usd > 0 ? '#10b98144' : '#47556933'}`,
            fontFamily: 'JetBrains Mono, monospace',
          }}>
            ${step.step_cost_usd.toFixed(5)}
          </span>
        )}

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

      {/* Epistemic Abstention Warning Card */}
      {isAbstained && (
        <div style={{
          background: 'rgba(245, 158, 11, 0.15)',
          border: '1px solid #f59e0b',
          borderRadius: '6px',
          padding: '8px 12px',
          marginBottom: '8px',
          color: '#fbbf24',
          fontSize: '12px',
          fontWeight: '600',
          display: 'flex',
          alignItems: 'center',
          gap: '6px',
        }}>
          🛡️ EPISTEMIC ABSTENTION: Agent identified insufficient context or missing data and gracefully refused to speculate.
        </div>
      )}

      {/* Re-Plan Diff Block */}
      {replanDiff && <ReplanDiffCard diff={replanDiff} />}

      <div style={{
        fontSize: '13px',
        color: '#e2e8f0',
        lineHeight: '1.6',
        whiteSpace: 'pre-wrap',
        wordBreak: 'break-word',
      }}>
        {step.type === 'done' ? formatDoneSummary(step.content) : step.content}
      </div>

      {/* Compact Run Report Card */}
      {step.type === 'done' && reportCard && <ReportCard reportCard={reportCard} />}
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

export default function AgentPanel({ onTaskMutated, conversationId }) {
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
  const [proactiveBriefing, setProactiveBriefing] = useState(null)
  const [triggeringNightly, setTriggeringNightly] = useState(false)
  const [runsList, setRunsList] = useState([])
  const [showHistory, setShowHistory] = useState(false)
  const [copyFeedback, setCopyFeedback] = useState(false)
  const traceEndRef = useRef(null)
  const abortRef = useRef(null)

  const getApiBase = () => {
    return window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1'
      ? 'http://127.0.0.1:8000'
      : ''
  }

  const fetchRunsHistory = async () => {
    try {
      const res = await fetch(`${getApiBase()}/api/agent/runs?limit=25`)
      if (res.ok) {
        const data = await res.json()
        setRunsList(data.runs || [])
      }
    } catch {
      // ignore
    }
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

  const fetchProactiveBriefing = async () => {
    try {
      const res = await fetch(`${getApiBase()}/api/agent/proactive-briefing`)
      if (res.ok) {
        const data = await res.json()
        if (data.found) {
          setProactiveBriefing(data)
        }
      }
    } catch {
      // ignore
    }
  }

  const triggerNightlyJob = async () => {
    setTriggeringNightly(true)
    try {
      const res = await fetch(`${getApiBase()}/api/agent/trigger-nightly`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': 'Bearer dev-token',
        },
      })
      if (res.ok) {
        await fetchProactiveBriefing()
        await fetchActivity()
      }
    } catch {
      // ignore
    } finally {
      setTriggeringNightly(false)
    }
  }

  const loadProactiveBriefingTrace = () => {
    if (proactiveBriefing && proactiveBriefing.accumulated_steps) {
      setSteps(proactiveBriefing.accumulated_steps)
      setCurrentRunId(proactiveBriefing.run_id)
      setGoal(proactiveBriefing.goal || '')
    }
  }

  useEffect(() => {
    fetchActivity()
    fetchCritiqueStats()
    fetchProactiveBriefing()
    fetchRunsHistory()
  }, [])

  // Auto-scroll to bottom as new steps appear
  useEffect(() => {
    if (traceEndRef.current) {
      traceEndRef.current.scrollIntoView({ behavior: 'smooth' })
    }
  }, [steps])

  const loadPastRun = (run) => {
    setGoal(run.goal || '')
    setCurrentRunId(run.id)
    setSteps(run.steps || [])
    setShowHistory(false)
  }

  const copyTraceAsMarkdown = () => {
    const totalCost = steps.reduce((sum, s) => sum + (s.step_cost_usd || 0), 0)
    const mdLines = [
      `# 🧭 Compass Agent Trace — ${goal || 'Goal'}`,
      `**Run ID**: \`${currentRunId || 'unknown'}\``,
      `**Total Steps**: ${steps.length}`,
      `**Estimated Cost**: $${totalCost.toFixed(5)} USD (Nebius Token Factory)`,
      '',
      '---',
      '',
    ]
    steps.forEach((s) => {
      const icon = STEP_STYLES[s.type]?.icon || '•'
      const label = STEP_STYLES[s.type]?.label || s.type.toUpperCase()
      mdLines.push(`### ${icon} Step ${s.step}: ${label} ${s.model_tier ? `(\`${s.model_tier}\`)` : ''}`)
      if (s.tool) {
        mdLines.push(`**Tool**: \`${s.tool}\``)
        if (s.args) {
          mdLines.push('```json')
          mdLines.push(JSON.stringify(s.args, null, 2))
          mdLines.push('```')
        }
      }
      if (s.content) {
        mdLines.push(`> ${s.content}`)
      }
      mdLines.push('')
    })
    navigator.clipboard.writeText(mdLines.join('\n'))
    setCopyFeedback(true)
    setTimeout(() => setCopyFeedback(false), 2000)
  }

  const streamFromEndpoint = async (payload) => {
    setIsRunning(true)
    const controller = new AbortController()
    abortRef.current = controller

    try {
      const apiBase = getApiBase()
      const reqPayload = { ...payload }
      if (conversationId && !reqPayload.conversation_id) {
        reqPayload.conversation_id = conversationId
      }

      const response = await fetch(`${apiBase}/api/agent/run`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(reqPayload),
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
      fetchRunsHistory()
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
    onTaskMutated?.()
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
        onTaskMutated?.()
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
        },
        body: JSON.stringify({ audit_log_id: auditLogId }),
      })
      const data = await res.json()
      if (res.ok && data.status === 'ok') {
        setUndoStatus(data.message || 'Action reverted')
        fetchActivity()
        onTaskMutated?.()
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
        {/* Proactive Autonomous Overnight Briefing Banner */}
        {proactiveBriefing && (
          <div style={{
            background: 'linear-gradient(135deg, rgba(30, 41, 59, 0.8), rgba(15, 23, 42, 0.95))',
            border: '1px solid #38bdf855',
            borderRadius: '8px',
            padding: '10px 14px',
            marginBottom: '12px',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            gap: '12px',
          }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
              <span style={{ fontSize: '20px' }}>🌙</span>
              <div>
                <div style={{ fontSize: '12px', fontWeight: '700', color: '#38bdf8', letterSpacing: '0.03em' }}>
                  Autonomous Overnight Briefing Ready
                </div>
                <div style={{ fontSize: '11px', color: '#94a3b8' }}>
                  Generated by Nightly Consolidation Worker ({proactiveBriefing.accumulated_steps?.length || 0} reasoning steps · {proactiveBriefing.run_id})
                </div>
              </div>
            </div>
            <div style={{ display: 'flex', gap: '8px' }}>
              <button
                id="load-proactive-briefing-btn"
                onClick={loadProactiveBriefingTrace}
                style={{
                  padding: '5px 12px',
                  background: '#0284c7',
                  border: 'none',
                  borderRadius: '6px',
                  color: '#fff',
                  fontSize: '11px',
                  fontWeight: '600',
                  cursor: 'pointer',
                  display: 'flex',
                  alignItems: 'center',
                  gap: '4px',
                }}
              >
                📥 View Overnight Trace
              </button>
              <button
                id="trigger-nightly-btn"
                onClick={triggerNightlyJob}
                disabled={triggeringNightly}
                style={{
                  padding: '5px 10px',
                  background: '#1e293b',
                  border: '1px solid #334155',
                  borderRadius: '6px',
                  color: '#94a3b8',
                  fontSize: '11px',
                  cursor: 'pointer',
                }}
                title="Trigger nightly consolidation job on-demand"
              >
                {triggeringNightly ? '⏳ Running...' : '↻ Run Job Now'}
              </button>
            </div>
          </div>
        )}

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

          <button
            id="agent-history-toggle-btn"
            onClick={() => { fetchRunsHistory(); setShowHistory(!showHistory) }}
            style={{
              padding: '10px 14px',
              background: showHistory ? '#334155' : '#1e293b',
              border: '1px solid #334155',
              borderRadius: '8px',
              color: '#94a3b8',
              fontSize: '13px',
              fontWeight: '600',
              cursor: 'pointer',
              whiteSpace: 'nowrap',
              display: 'flex',
              alignItems: 'center',
              gap: '6px',
            }}
            title="Toggle Agent Run History"
          >
            📜 History ({runsList.length})
          </button>

          {steps.length > 0 && (
            <button
              id="agent-copy-trace-btn"
              onClick={copyTraceAsMarkdown}
              style={{
                padding: '10px 14px',
                background: '#1e293b',
                border: '1px solid #334155',
                borderRadius: '8px',
                color: copyFeedback ? '#34d399' : '#94a3b8',
                fontSize: '13px',
                fontWeight: '600',
                cursor: 'pointer',
                whiteSpace: 'nowrap',
              }}
              title="Copy execution trace as Markdown"
            >
              {copyFeedback ? '✓ Copied' : '📋 Copy Trace'}
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

            <button
              id="agent-demo-tri-domain-btn"
              onClick={() => {
                const demoGoal = "What should I deprioritize this week, given my code debt and upcoming exams?"
                setGoal(demoGoal)
                runAgent(demoGoal)
              }}
              style={{
                padding: '5px 12px',
                background: 'linear-gradient(135deg, rgba(37, 99, 235, 0.25), rgba(147, 51, 234, 0.25))',
                border: '1px solid #3b82f688',
                borderRadius: '14px',
                color: '#60a5fa',
                fontSize: '11px',
                fontWeight: '700',
                cursor: 'pointer',
                display: 'flex',
                alignItems: 'center',
                gap: '4px',
                transition: 'all 0.2s',
              }}
              title="Chains query_tasks, query_code_context, and query_coursework_notes in a single run"
            >
              ⚡ 3-Domain Triage
            </button>

            <button
              id="agent-demo-abstain-btn"
              onClick={() => {
                const demoGoal = "What is the final grade weighting and curve formula for the Quantum Computing midterm?"
                setGoal(demoGoal)
                runAgent(demoGoal)
              }}
              style={{
                padding: '5px 12px',
                background: 'linear-gradient(135deg, rgba(245, 158, 11, 0.25), rgba(217, 119, 6, 0.25))',
                border: '1px solid #f59e0b88',
                borderRadius: '14px',
                color: '#fbbf24',
                fontSize: '11px',
                fontWeight: '700',
                cursor: 'pointer',
                display: 'flex',
                alignItems: 'center',
                gap: '4px',
                transition: 'all 0.2s',
              }}
              title="Demonstrates epistemic abstention when required context is missing"
            >
              🛡️ Epistemic Abstention
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
        {/* Run History Flyout Drawer */}
        {showHistory && (
          <div style={{
            marginBottom: '16px',
            background: 'linear-gradient(135deg, rgba(15, 23, 42, 0.95), rgba(30, 41, 59, 0.95))',
            border: '1px solid #334155',
            borderRadius: '8px',
            padding: '14px',
            boxShadow: '0 8px 24px rgba(0, 0, 0, 0.4)',
          }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '10px' }}>
              <span style={{ fontSize: '12px', fontWeight: '700', color: '#e2e8f0', textTransform: 'uppercase', letterSpacing: '0.05em' }}>
                📜 Past Agent Runs ({runsList.length})
              </span>
              <button
                onClick={() => setShowHistory(false)}
                style={{ background: 'transparent', border: 'none', color: '#94a3b8', cursor: 'pointer', fontSize: '14px' }}
              >
                ✕
              </button>
            </div>
            {runsList.length === 0 ? (
              <div style={{ fontSize: '12px', color: '#64748b', fontStyle: 'italic', padding: '12px 0', textAlign: 'center' }}>
                No past agent runs recorded yet. Run any goal above to see persistent execution history.
              </div>
            ) : (
              <div style={{ display: 'flex', flexDirection: 'column', gap: '6px', maxHeight: '220px', overflowY: 'auto' }}>
                {runsList.map(r => (
                  <div
                    key={r.id}
                    onClick={() => loadPastRun(r)}
                    style={{
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'space-between',
                      padding: '8px 12px',
                      background: currentRunId === r.id ? 'rgba(37, 99, 235, 0.2)' : 'rgba(30, 41, 59, 0.6)',
                      border: `1px solid ${currentRunId === r.id ? '#2563eb' : '#334155'}`,
                      borderRadius: '6px',
                      cursor: 'pointer',
                      transition: 'all 0.15s',
                    }}
                  >
                    <div style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', maxWidth: '70%' }}>
                      <span style={{ fontSize: '12px', color: '#f1f5f9', fontWeight: '500' }}>{r.goal || 'Untitled Goal'}</span>
                      <div style={{ fontSize: '10px', color: '#64748b', fontFamily: 'monospace', display: 'flex', alignItems: 'center', gap: '4px' }}>
                        <span>{r.id} · {r.created_at ? r.created_at.slice(0, 19).replace('T', ' ') : ''}</span>
                        {r.conversation_id && (
                          <span style={{ color: '#60a5fa', background: 'rgba(37, 99, 235, 0.15)', padding: '1px 4px', borderRadius: '4px' }}>
                            💬 conv:{r.conversation_id.slice(0, 8)}
                          </span>
                        )}
                      </div>
                    </div>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                      <span style={{ fontSize: '11px', color: '#94a3b8' }}>{r.steps_count} steps</span>
                      <span style={{
                        fontSize: '9px',
                        fontWeight: '700',
                        padding: '2px 6px',
                        borderRadius: '4px',
                        background: r.status === 'completed' ? 'rgba(34, 197, 94, 0.2)' : r.status === 'paused' ? 'rgba(234, 179, 8, 0.2)' : 'rgba(100, 116, 139, 0.2)',
                        color: r.status === 'completed' ? '#4ade80' : r.status === 'paused' ? '#facc15' : '#94a3b8',
                      }}>
                        {r.status.toUpperCase()}
                      </span>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}

        {/* Animated Step Progress Bar */}
        {(steps.length > 0 || isRunning) && (
          <div style={{
            marginBottom: '14px',
            padding: '10px 14px',
            background: 'rgba(15, 23, 42, 0.7)',
            border: '1px solid #1e293b',
            borderRadius: '8px',
          }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '6px', fontSize: '11px', color: '#94a3b8' }}>
              <span style={{ display: 'flex', alignItems: 'center', gap: '6px', fontWeight: '600', color: isRunning ? '#38bdf8' : '#34d399' }}>
                <span style={{ display: 'inline-block', width: '6px', height: '6px', borderRadius: '50%', background: isRunning ? '#38bdf8' : '#34d399', animation: isRunning ? 'pulse 1s infinite' : 'none' }} />
                {isRunning ? 'Agent Execution in Progress...' : 'Execution Plan Ready'}
              </span>
              <span style={{ fontFamily: 'JetBrains Mono, monospace', fontSize: '11px' }}>
                Step {steps.length} / 8 · Total: ${(steps.reduce((sum, s) => sum + (s.step_cost_usd || 0), 0)).toFixed(5)} USD
              </span>
            </div>
            <div style={{ width: '100%', height: '4px', background: '#1e293b', borderRadius: '2px', overflow: 'hidden' }}>
              <div style={{
                width: `${Math.min(100, (steps.length / 8) * 100)}%`,
                height: '100%',
                background: isRunning ? 'linear-gradient(90deg, #2563eb, #38bdf8)' : '#10b981',
                transition: 'width 0.3s ease',
                boxShadow: isRunning ? '0 0 8px #38bdf8' : 'none',
              }} />
            </div>
          </div>
        )}

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

        {/* Cost Efficiency Comparison Card */}
        {steps.some(s => s.type === 'done') && (
          <div style={{
            margin: '14px 0',
            padding: '12px 16px',
            background: 'linear-gradient(135deg, rgba(16, 185, 129, 0.1), rgba(14, 165, 233, 0.1))',
            border: '1px solid rgba(52, 211, 153, 0.3)',
            borderRadius: '8px',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            gap: '12px',
          }}>
            <div>
              <div style={{ fontSize: '12px', fontWeight: '700', color: '#34d399', letterSpacing: '0.02em', display: 'flex', alignItems: 'center', gap: '6px' }}>
                <span>⚡</span> Nebius Token Factory Cost Efficiency
              </div>
              <div style={{ fontSize: '11px', color: '#94a3b8', marginTop: '2px' }}>
                This {steps.length}-step run cost <strong style={{ color: '#e2e8f0' }}>${(steps.reduce((sum, s) => sum + (s.step_cost_usd || 0), 0)).toFixed(5)}</strong> on Nebius · Equivalent on GPT-4o: <strong style={{ color: '#f87171' }}>~${((steps.reduce((sum, s) => sum + (s.step_cost_usd || 0), 0)) * 36).toFixed(4)}</strong> (~36x cost reduction)
              </div>
            </div>
            <span style={{
              padding: '4px 8px',
              background: 'rgba(16, 185, 129, 0.2)',
              borderRadius: '6px',
              border: '1px solid #10b98155',
              color: '#4ade80',
              fontSize: '11px',
              fontWeight: '700',
              fontFamily: 'monospace',
              whiteSpace: 'nowrap',
            }}>
              97.2% SAVINGS
            </span>
          </div>
        )}

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
