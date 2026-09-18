import React, { useState, useEffect, useRef, useCallback } from 'react'
import Sidebar from './components/Sidebar'
import Timeline from './components/Timeline'
import ChatPanel from './components/ChatPanel'
import AgentPanel from './components/AgentPanel'
import CalendarView from './components/CalendarView'
import {
  checkBackendHealth,
  fetchTasks,
  sendQueryToAssistant,
  fetchUsageSummary,
  fetchCurrentUser,
  getGoogleOAuthConnectUrl,
  disconnectCalendar,
} from './api/client'

export default function App() {
  const [tasks, setTasks] = useState([])
  const [activeTab, setActiveTab] = useState('timeline')
  const [selectedDomain, setSelectedDomain] = useState('all')
  const [backendStatus, setBackendStatus] = useState('Connecting...')
  const [conversationId, setConversationId] = useState(null)
  const [usageStats, setUsageStats] = useState(null)
  const [currentUser, setCurrentUser] = useState(null)
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
    fetchCurrentUser().then(u => {
      if (isMounted && u) setCurrentUser(u)
    })

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
        usageBadge={usageBadge}
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
            <button
              id="tab-calendar"
              onClick={() => setActiveTab('calendar')}
              style={{
                padding: '7px 14px',
                borderRadius: '6px',
                border: 'none',
                background: activeTab === 'calendar' ? '#1e293b' : 'transparent',
                color: activeTab === 'calendar' ? '#fff' : '#64748b',
                cursor: 'pointer',
                fontWeight: '500',
                fontSize: '13px'
              }}>
              🗓️ Schedule & Calendar
            </button>
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: '14px' }}>
            {/* P0.2: Live usage counter — updates after every chat message */}
            <div id="usage-badge" className="header-model-badge" style={{ fontSize: '11px', color: '#64748b', fontFamily: 'JetBrains Mono, monospace' }}>
              {usageBadge}
            </div>

            {/* Google User Profile / Login Pill */}
            {currentUser && currentUser.authenticated ? (
              <div
                id="user-profile-badge"
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: '8px',
                  background: 'rgba(30, 41, 59, 0.8)',
                  border: '1px solid #334155',
                  padding: '4px 10px',
                  borderRadius: '20px',
                  fontSize: '12px',
                  color: '#e2e8f0',
                }}>
                <span style={{
                  width: '7px',
                  height: '7px',
                  borderRadius: '50%',
                  background: '#10b981',
                  boxShadow: '0 0 6px #10b981',
                }} />
                <span style={{ fontWeight: '500', color: '#f8fafc', maxWidth: '180px', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                  {currentUser.email}
                </span>
                <button
                  onClick={async () => {
                    await disconnectCalendar()
                    setCurrentUser({ authenticated: false, email: '' })
                  }}
                  title="Sign out / Disconnect"
                  style={{
                    background: 'transparent',
                    border: 'none',
                    color: '#94a3b8',
                    cursor: 'pointer',
                    fontSize: '11px',
                    padding: '0 2px',
                  }}>
                  ✕
                </button>
              </div>
            ) : (
              <a
                id="header-btn-google-login"
                href={getGoogleOAuthConnectUrl()}
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: '6px',
                  padding: '5px 12px',
                  borderRadius: '8px',
                  background: 'rgba(59, 130, 246, 0.12)',
                  border: '1px solid rgba(59, 130, 246, 0.35)',
                  color: '#60a5fa',
                  fontSize: '12px',
                  fontWeight: '500',
                  textDecoration: 'none',
                  cursor: 'pointer',
                  transition: 'all 0.15s ease',
                }}>
                <svg width="13" height="13" viewBox="0 0 24 24" fill="currentColor">
                  <path d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z" fill="#4285F4"/>
                  <path d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z" fill="#34A853"/>
                  <path d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.06H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.94l2.85-2.22.81-.63z" fill="#FBBC05"/>
                  <path d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.06l3.66 2.84c.87-2.6 3.3-4.52 6.16-4.52z" fill="#EA4335"/>
                </svg>
                Sign in with Google
              </a>
            )}
          </div>
        </header>

        {activeTab === 'timeline' ? (
          <Timeline
            tasks={tasks}
            activeDomain={selectedDomain}
            onSelectDomain={setSelectedDomain}
          />
        ) : activeTab === 'calendar' ? (
          <CalendarView
            tasks={tasks}
            activeDomain={selectedDomain}
            onTasksUpdated={() => {
              loadTasks(selectedDomain)
              refreshUsage()
            }}
          />
        ) : activeTab === 'agent' ? (
          <AgentPanel
            onTaskMutated={() => {
              loadTasks(selectedDomain)
              refreshUsage()
            }}
            conversationId={conversationId}
          />
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

