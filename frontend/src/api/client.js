// Compass API Client
// In production, use same-origin relative URLs ('') so Vercel transparently proxies
// all /health and /api/* requests to Render, making it 100% immune to Brave Shields & ad-blockers.
// In development, fall back to VITE_API_BASE_URL or http://localhost:8000.
const API_BASE = (
  import.meta.env.DEV
    ? (import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000')
    : ''
).replace(/\/$/, '')

export const FALLBACK_TASKS = [
  {
    id: '1',
    title: 'Submit Nebius Token Factory Benchmark',
    domain: 'hackathon',
    project: 'Compass',
    countdown: '2d left (Friday)',
    tags: ['nebius', 'vector', 'benchmark'],
    vector_dim: 768,
    timestamp: 'Just now'
  },
  {
    id: '2',
    title: 'Configured Matryoshka 768-dim embeddings with Nebius Token Factory',
    domain: 'code',
    project: 'Compass',
    countdown: 'Logged from CLI',
    tags: ['qwen3', 'pgvector', 'hnsw'],
    vector_dim: 768,
    timestamp: '2 mins ago'
  },
  {
    id: '3',
    title: 'CS 61C — RISC-V Pipeline Synthesis Report',
    domain: 'coursework',
    project: 'CS 61C',
    countdown: '1d left (Thursday)',
    tags: ['hardware', 'riscv', 'architecture'],
    vector_dim: 768,
    timestamp: '1 hour ago'
  },
  {
    id: '4',
    title: 'Implement Nemotron-3 Nano sub-400ms router function',
    domain: 'code',
    project: 'Compass Core',
    countdown: 'Completed',
    tags: ['nemotron', 'router', 'latency'],
    vector_dim: 768,
    timestamp: '3 hours ago'
  }
]

/**
 * Health check ping — dynamically reports Neon connection or fallback status.
 */
export async function checkBackendHealth() {
  try {
    const controller = new AbortController()
    const timeoutId = setTimeout(() => controller.abort(), 4000)

    const res = await fetch(`${API_BASE}/health`, {
      method: 'GET',
      signal: controller.signal
    })
    clearTimeout(timeoutId)

    if (!res.ok) {
      return 'Backend Error • HTTP ' + res.status
    }

    const data = await res.json()
    if (data.db_connected || data.status === 'ok') {
      return 'Live • Neon Connected'
    }
    return 'Edge Online • Syncing'
  } catch {
    return 'Backend Offline • Connection Refused'
  }
}

/**
 * Fetch synchronized task list from Neon PostgreSQL.
 * Accepts an optional domain string to issue a genuine server-side filtered request.
 * Returns empty array if database is empty; falls back to demo tasks only if server is unreachable.
 */
export async function fetchTasks(domain) {
  try {
    const controller = new AbortController()
    const timeoutId = setTimeout(() => controller.abort(), 4000)

    // Build URL — append ?domain=<X> when a specific domain is selected so the
    // backend filters at the SQL level, not the client. This is what makes the
    // filter buttons trigger real server-side requests instead of client-side slicing.
    const url = domain && domain !== 'all'
      ? `${API_BASE}/api/tasks?domain=${encodeURIComponent(domain)}`
      : `${API_BASE}/api/tasks`

    const res = await fetch(url, {
      signal: controller.signal
    })
    clearTimeout(timeoutId)

    if (!res.ok) {
      return FALLBACK_TASKS
    }

    const data = await res.json()
    if (Array.isArray(data)) {
      return data
    }
    return FALLBACK_TASKS
  } catch {
    return FALLBACK_TASKS
  }
}

/**
 * Fetch live usage summary (total calls, tokens, cost) from /api/usage/summary.
 * Public endpoint — no auth required. Returns null on failure.
 */
export async function fetchUsageSummary() {
  try {
    const controller = new AbortController()
    const timeoutId = setTimeout(() => controller.abort(), 3000)
    const res = await fetch(`${API_BASE}/api/usage/summary`, { signal: controller.signal })
    clearTimeout(timeoutId)
    if (!res.ok) return null
    return await res.json()
  } catch {
    return null
  }
}

/**
 * Send a chat message to the Nebius-powered assistant.
 * Passes conversation_id for multi-turn memory.
 * Returns { response, conversation_id } on success.
 */
export async function sendQueryToAssistant(prompt, conversationId) {
  try {
    const controller = new AbortController()
    const timeoutId = setTimeout(() => controller.abort(), 12000)

    const body = { message: prompt }
    if (conversationId) {
      body.conversation_id = conversationId
    }

    const res = await fetch(`${API_BASE}/api/chat`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
      signal: controller.signal
    })
    clearTimeout(timeoutId)

    if (res.ok) {
      const data = await res.json()
      const text = data.response || data.message || ''
      if (text) {
        return {
          response: text,
          conversation_id: data.conversation_id || conversationId || null
        }
      }
    }
  } catch (err) {
    console.warn('[Compass Chat] Backend unreachable or timeout.', err)
  }

    // Friendly fallback when backend is offline
    return {
      response: "I'm having trouble connecting right now. Please make sure the backend is running and try again!",
      conversation_id: conversationId || null
    }
  }

/**
 * Stream chat tokens via Server-Sent Events (SSE) from /api/chat/stream.
 * Dispatches incremental tokens via onToken, completion metadata via onComplete,
 * and errors via onError.
 */
export async function streamQueryFromAssistant(prompt, conversationId, { onToken, onComplete, onError } = {}) {
  try {
    const body = { message: prompt }
    if (conversationId) {
      body.conversation_id = conversationId
    }

    const res = await fetch(`${API_BASE}/api/chat/stream`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    })

    if (!res.ok) {
      throw new Error(`SSE endpoint returned HTTP ${res.status}`)
    }

    const reader = res.body.getReader()
    const decoder = new TextDecoder()
    let buffer = ''
    let fullResponse = ''
    let lastConvId = conversationId || null
    let lastSkill = null

    while (true) {
      const { done, value } = await reader.read()
      if (done) break

      buffer += decoder.decode(value, { stream: true })
      const lines = buffer.split('\n')
      buffer = lines.pop() || ''

      for (const line of lines) {
        const trimmed = line.trim()
        if (!trimmed || !trimmed.startsWith('data:')) continue
        const jsonStr = trimmed.slice(5).trim()
        if (!jsonStr) continue
        try {
          const evt = JSON.parse(jsonStr)
          if (evt.type === 'token') {
            fullResponse += evt.value
            if (onToken) onToken(evt.value, fullResponse)
          } else if (evt.type === 'done') {
            if (evt.conversation_id) lastConvId = evt.conversation_id
            if (evt.skill_used) lastSkill = evt.skill_used
          } else if (evt.type === 'error') {
            throw new Error(evt.message || 'Stream error')
          }
        } catch (e) {
          console.warn('[Compass SSE Parse Error]', e, jsonStr)
        }
      }
    }

    if (onComplete) {
      onComplete({
        response: fullResponse,
        conversation_id: lastConvId,
        skill_used: lastSkill,
      })
    }
    return {
      response: fullResponse,
      conversation_id: lastConvId,
      skill_used: lastSkill,
    }
  } catch (err) {
    if (onError) {
      onError(err)
    } else {
      throw err
    }
  }
}

// ---------------------------------------------------------------------------
// Calendar & Dynamic Scheduling API
// ---------------------------------------------------------------------------

export async function fetchCalendarStatus() {
  try {
    const res = await fetch(`${API_BASE}/api/calendar/status`)
    if (!res.ok) return { connected: false, mode: 'demo', account_email: 'demo-scholar@compass.ai', is_simulated: true }
    const data = await res.json()
    return data.calendar || { connected: false, mode: 'demo', is_simulated: true }
  } catch {
    return { connected: false, mode: 'demo', account_email: 'demo-scholar@compass.ai', is_simulated: true }
  }
}

export function getGoogleOAuthConnectUrl() {
  return `${API_BASE}/api/calendar/connect`
}

export async function disconnectCalendar() {
  try {
    const res = await fetch(`${API_BASE}/api/calendar/disconnect`, { method: 'POST' })
    return await res.json()
  } catch {
    return { status: 'ok' }
  }
}


export async function fetchCalendarAvailability(startDate, endDate) {
  try {
    let url = `${API_BASE}/api/calendar/availability`
    const params = new URLSearchParams()
    if (startDate) params.append('start_date', startDate)
    if (endDate) params.append('end_date', endDate)
    if (params.toString()) url += `?${params.toString()}`

    const res = await fetch(url)
    if (!res.ok) throw new Error(`HTTP ${res.status}`)
    const json = await res.json()
    return json.data || json
  } catch (err) {
    console.warn('[Compass Calendar Availability Fallback]', err)
    return { busy_intervals: [], free_windows: [] }
  }
}

export async function proposeSchedule({ targetDate, domain, taskIds } = {}) {
  const payload = {}
  if (targetDate) payload.target_date = targetDate
  if (domain && domain !== 'all') payload.domain = domain
  if (taskIds && taskIds.length > 0) payload.task_ids = taskIds

  const res = await fetch(`${API_BASE}/api/schedule/propose`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
  if (!res.ok) throw new Error(`HTTP ${res.status}`)
  const json = await res.json()
  return json.data || json
}

export async function commitSchedule(assignments, rationale = 'Committed via Schedule View') {
  const res = await fetch(`${API_BASE}/api/schedule/commit`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ assignments, rationale }),
  })
  if (!res.ok) throw new Error(`HTTP ${res.status}`)
  const json = await res.json()
  return json.data || json
}

export async function fetchSchedulingPreferences() {
  try {
    const res = await fetch(`${API_BASE}/api/calendar/preferences`)
    if (!res.ok) throw new Error(`HTTP ${res.status}`)
    return await res.json()
  } catch {
    return {
      work_start_time: '09:00:00',
      work_end_time: '18:00:00',
      work_days: [1, 2, 3, 4, 5],
      buffer_minutes: 15,
      preferred_focus: 'morning',
    }
  }
}

export function getCalendarExportUrl(domain) {
  if (domain && domain !== 'all') {
    return `${API_BASE}/api/calendar/export.ics?domain=${encodeURIComponent(domain)}`
  }
  return `${API_BASE}/api/calendar/export.ics`
}

export async function checkReactiveSchedule(currentTime = null) {
  const body = currentTime ? { current_time: currentTime } : {}
  const res = await fetch(`${API_BASE}/api/schedule/reactive-check`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!res.ok) throw new Error(`HTTP ${res.status}`)
  return await res.json()
}

export async function fetchScheduleConflicts() {
  const res = await fetch(`${API_BASE}/api/schedule/conflicts`)
  if (!res.ok) throw new Error(`HTTP ${res.status}`)
  return await res.json()
}


