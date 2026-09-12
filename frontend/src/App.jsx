import React, { useState, useEffect, useRef, useCallback } from 'react'
import Sidebar from './components/Sidebar'
import Timeline from './components/Timeline'
import ChatPanel from './components/ChatPanel'
import AgentPanel from './components/AgentPanel'
import { checkBackendHealth, fetchTasks, sendQueryToAssistant, fetchUsageSummary } from './api/client'

export default function App() {
  const [tasks, setTasks] = useState([])
  const [activeTab, setActiveTab] = useState('timeline')
  const [selectedDomain, setSelectedDomain] = useState('all')
  const [backendStatus, setBackendStatus] = useState('Connecting...')
  const [conversationId, setConversationId] = useState(null)
  const [usageStats, setUsageStats] = useState(null)
  const [messages, setMessages] = useState([
    {
      role: 'assistant',
      text: "Hey! I'm Compass, your productivity copilot. I can track tasks, recall code context, synthesize cross-domain roadmaps, and search the web. What's on your mind?"
    }
  ])
  const [isTyping, setIsTyping] = useState(false)

  // Keep a ref to the latest tasks state for stable diffing without triggering interval re-creations
  const tasksRef = useRef([])
  tasksRef.current = tasks

  // Refresh usage stats from the backend (public endpoint, no auth required)
  const refreshUsage = useCallback(async () => {
    const stats = await fetchUsageSummary()
    if (stats) setUsageStats(stats)
  }, [])

  // P0.1 FIX: Domain-aware task fetcher — fires a NEW server-side request with
  // ?domain=<X> query param every time selectedDomain changes, instead of
  // client-side array filtering on stale data.
  const loadTasks = useCallback(async (domain) => {
    try {
      const incomingTasks = await fetchTasks(domain)
      if (!Array.isArray(incomingTasks)) return

      const currentTasks = tasksRef.current
      const hasLengthChanged = incomingTasks.length !== currentTasks.length
      const hasContentChanged = incomingTasks.some((task, i) => {
        const cur = currentTasks[i]
        return !cur || cur.id !== task.id || cur.title !== task.title || cur.countdown !== task.countdown
      })
      if (hasLengthChanged || hasContentChanged) {
        setTasks(incomingTasks)
      }
    } catch {
      // Silently preserve current view during transient connection blips
    }
  }, [])

  // Re-fetch tasks from server whenever the domain filter changes
  useEffect(() => {
    loadTasks(selectedDomain)
  }, [selectedDomain, loadTasks])

  useEffect(() => {
    let isMounted = true

    // Health Polling (Every 10 seconds)
    const pollHealth = async () => {
      try {
        const status = await checkBackendHealth()
        if (isMounted) setBackendStatus(status)
      } catch {
        if (isMounted) setBackendStatus('Demo Mode • Mock Memory')
      }
    }

    // Task Polling (Every 3000ms with Clean State Merge) — uses current domain filter
    const pollTasks = () => {
      if (isMounted) loadTasks(selectedDomain)
    }

    // Immediate initial sync
    pollHealth()
    refreshUsage()

    // 1. Task polling interval: 3000ms
    const taskInterval = setInterval(pollTasks, 3000)

    // 2. Health check polling interval: 10,000ms (10 seconds)
    const healthInterval = setInterval(pollHealth, 10000)

    // Component Cleanup: clear all interval timers on unmount
    return () => {
      isMounted = false
      clearInterval(taskInterval)
      clearInterval(healthInterval)
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const domainCounts = {
    hackathon: tasks.filter(t => t.domain === 'hackathon').length,
    coursework: tasks.filter(t => t.domain === 'coursework').length,
    code: tasks.filter(t => t.domain === 'code').length,
    general: tasks.filter(t => t.domain === 'general').length,
  }

  const handleSendMessage = async (userText) => {
    setIsTyping(true)

    const result = await sendQueryToAssistant(userText, conversationId)

    setIsTyping(false)

    // Update conversation_id for multi-turn threading
    if (result.conversation_id && result.conversation_id !== conversationId) {
      setConversationId(result.conversation_id)
    }

    // P0.2 FIX: Refresh usage counter after every chat turn so the header
    // reflects real token consumption instead of showing a static string.
    refreshUsage()

    return result.response
  }

  // P0.2: Build the live header badge text with micro-dollar precision
  const usageBadge = usageStats
    ? `⚡ ${usageStats.total_requests ?? 0} calls · $${(usageStats.total_estimated_cost_usd ?? 0).toFixed(5)}`
    : 'Nebius • Nemotron-3'

  return (
    <div style={{ display: 'flex', height: '100vh', width: '100vw', background: '#0b0f17', overflow: 'hidden' }}>
      <Sidebar
        activeDomain={selectedDomain}
        onSelectDomain={setSelectedDomain}
        domainCounts={domainCounts}
        backendStatus={backendStatus}
        activeTab={activeTab}
        onSelectTab={setActiveTab}
      />

      <main style={{ flex: 1, display: 'flex', flexDirection: 'column', background: '#0b0f17', minWidth: 0, overflow: 'hidden' }}>
        <header style={{ height: '60px', borderBottom: '1px solid #1e293b', display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '0 20px', flexShrink: 0 }}>
          <div style={{ display: 'flex', gap: '8px' }}>
            <button
              id="tab-timeline"
              onClick={() => setActiveTab('timeline')}
              style={{
                padding: '7px 14px',
                borderRadius: '6px',
                border: 'none',
                background: activeTab === 'timeline' ? '#1e293b' : 'transparent',
                color: activeTab === 'timeline' ? '#fff' : '#64748b',
                cursor: 'pointer',
                fontWeight: '500',
                fontSize: '13px'
              }}>
              📅 Timeline Feed
            </button>
            <button
              id="tab-chat"
              onClick={() => setActiveTab('chat')}
              style={{
                padding: '7px 14px',
                borderRadius: '6px',
                border: 'none',
                background: activeTab === 'chat' ? '#1e293b' : 'transparent',
                color: activeTab === 'chat' ? '#fff' : '#64748b',
                cursor: 'pointer',
                fontWeight: '500',
                fontSize: '13px'
              }}>
              💬 Assistant Chat
            </button>
            <button
              id="tab-agent"
              onClick={() => setActiveTab('agent')}
              style={{
                padding: '7px 14px',
                borderRadius: '6px',
                border: 'none',
                background: activeTab === 'agent' ? '#1e293b' : 'transparent',
                color: activeTab === 'agent' ? '#fff' : '#64748b',
                cursor: 'pointer',
                fontWeight: '500',
                fontSize: '13px'
              }}>
              🧠 Agent Planner
            </button>
          </div>
          {/* P0.2: Live usage counter — updates after every chat message */}
          <div id="usage-badge" className="header-model-badge" style={{ fontSize: '11px', color: '#64748b', fontFamily: 'JetBrains Mono, monospace' }}>
            {usageBadge}
          </div>
        </header>

        {activeTab === 'timeline' ? (
          <Timeline
            tasks={tasks}
            activeDomain={selectedDomain}
            onSelectDomain={setSelectedDomain}
          />
        ) : activeTab === 'agent' ? (
          <AgentPanel />
        ) : (
          <ChatPanel
            messages={messages}
            setMessages={setMessages}
            conversationId={conversationId}
            setConversationId={setConversationId}
            onSendMessage={handleSendMessage}
            isTyping={isTyping}
            onChatComplete={refreshUsage}
          />
        )}
      </main>
    </div>
  )
}

