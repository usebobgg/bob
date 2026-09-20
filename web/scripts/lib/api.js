const TOKEN = document.querySelector('meta[name="app-token"]')?.content ?? ''

export class ApiError extends Error {
  constructor(message, status) {
    super(message)
    this.name = 'ApiError'
    this.status = status
  }
}

export const request = async (path, body) => {
  let response

  try {
    response = await fetch(path, {
      method: body === undefined ? 'GET' : 'POST',
      headers: { 'Content-Type': 'application/json', 'X-App-Token': TOKEN },
      body: body === undefined ? undefined : JSON.stringify(body)
    })
  } catch (E) {
    throw new ApiError('Bob is not running. Start it again, then reload this page.', 0)
  }

  const payload = await response.json().catch(() => ({}))

  if (!response.ok) {
    throw new ApiError(payload.error ?? 'Something went wrong.', response.status)
  }

  return payload
}

export const subscribe = (handlers) => {
  const source = new EventSource(`/api/events?token=${encodeURIComponent(TOKEN)}`)

  for (const [event, handler] of Object.entries(handlers)) {
    source.addEventListener(event, (message) => handler(JSON.parse(message.data)))
  }

  return source
}
