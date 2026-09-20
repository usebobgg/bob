import { createCommentList } from './components/comment-list.js'
import { createTerminal } from './components/terminal.js'
import { request, subscribe } from './lib/api.js'
import { createElement, requireElement } from './lib/dom.js'
import { describeReasons, formatStamp, plural } from './lib/format.js'

const SETTING_DEFAULTS = {
  minimum_duplicate_parents: 2,
  maximum_distinct_parents: 3,
  minimum_delete_delay_seconds: 3,
  maximum_delete_delay_seconds: 8
}

const VIEW_BY_PHASE = {
  idle: 'ready',
  scanning: 'scanning',
  review: 'review',
  deleting: 'deleting',
  done: 'done'
}

const STEP_BY_VIEW = {
  loading: 'connect',
  connect: 'connect',
  ready: 'scan',
  scanning: 'scan',
  review: 'review',
  deleting: 'review',
  done: 'done'
}

const STEP_ORDER = ['connect', 'scan', 'review', 'done']
const EXTRA_ROUTES = ['history', 'settings']

export const initApp = async () => {
  const title = requireElement('[data-title]')
  const notice = requireElement('[data-notice]')
  const progress = requireElement('[data-progress]')
  const reviewText = requireElement('[data-review-text]')
  const reviewActions = requireElement('[data-review-actions]')
  const reviewReset = requireElement('[data-review-reset]')
  const reviewAnother = requireElement('[data-review-another]')
  const confirm = requireElement('[data-confirm]')
  const deleteLabel = requireElement('[data-delete-label]')
  const confirmLabel = requireElement('[data-confirm-label]')
  const historyText = requireElement('[data-history-text]')
  const historyRuns = requireElement('[data-history-runs]')
  const settingsForm = requireElement('[data-form="settings"]')
  const filter = requireElement('[data-filter]')
  const commentSheet = requireElement('[data-sheet="comments"]')
  const guideSheet = requireElement('[data-sheet="guide"]')
  const sheetCount = requireElement('[data-sheet-count]')
  const sheetNoun = requireElement('[data-sheet-noun]')
  const sheetEmpty = requireElement('[data-sheet-empty]')
  const drawer = requireElement('[data-drawer]')
  const logToggle = requireElement('[data-log-toggle]')
  const logLabel = requireElement('[data-log-label]')
  const sidebar = requireElement('[data-sidebar]')
  const sidebarToggle = requireElement('[data-sidebar-toggle]')
  const sessionInitial = requireElement('[data-session-initial]')
  const dropzone = requireElement('[data-dropzone]')
  const dropzoneTitle = requireElement('[data-dropzone-title]')
  const urlInput = requireElement('#url-input')
  const cancelLogin = requireElement('[data-action="cancel-login"]')
  const sessionBlock = requireElement('[data-session]')
  const sessionHandle = requireElement('[data-session-handle]')
  const views = [...document.querySelectorAll('[data-view]')]
  const steps = [...document.querySelectorAll('[data-step]')]
  const routeLinks = [...document.querySelectorAll('[data-route-link]')]

  const terminal = createTerminal([requireElement('[data-terminal]')])
  const state = {
    route: '',
    phase: 'idle',
    session: null,
    isChangingLogin: false,
    isConfirming: false,
    comments: [],
    deletedIds: [],
    commentsById: new Map(),
    flagged: new Map(),
    kept: new Set(),
    topLevelCount: 0,
    replyCount: 0,
    deletedCount: 0,
    deleteTotal: 0,
    filter: 'flagged',
    settings: { ...SETTING_DEFAULTS },
    lastSettings: '',
    history: [],
    historyIndex: 0,
    sheetSource: '',
    instance: '',
    sequence: 0
  }

  const commentList = createCommentList({
    list: requireElement('[data-sheet-list]'),
    onKeepChange(commentId, isKept) {
      state.kept[isKept ? 'add' : 'delete'](commentId)
      render()
    }
  })

  const setSidebarCollapsed = (isCollapsed) => {
    sidebar.classList.toggle('sidebar--collapsed', isCollapsed)
    sidebarToggle.setAttribute('aria-expanded', String(!isCollapsed))
    sidebarToggle.setAttribute('aria-label', isCollapsed ? 'Expand the sidebar' : 'Collapse the sidebar')
    window.localStorage.setItem('bob-sidebar-collapsed', String(isCollapsed))
  }

  const selectedIds = () => [...state.flagged.keys()].filter((commentId) => !state.kept.has(commentId))

  const accountCount = (commentIds) => new Set(commentIds.map((commentId) => state.commentsById.get(commentId)?.user_id)).size

  const currentView = () => {
    if (EXTRA_ROUTES.includes(state.route)) {
      return state.route
    }

    if (!state.session || state.isChangingLogin) {
      return 'connect'
    }

    return VIEW_BY_PHASE[state.phase] ?? 'ready'
  }

  const setTitle = (strong, rest) => {
    title.replaceChildren(createElement('span', 'stage__title-strong', strong), document.createTextNode(rest))
  }

  const showNotice = (message, isAlert = true) => {
    notice.textContent = message
    notice.hidden = !message
    notice.classList.toggle('notice--alert', isAlert)
  }

  const setSheetCount = (count, noun) => {
    sheetCount.textContent = count.toLocaleString('en')
    sheetNoun.textContent = noun
    commentSheet.classList.toggle('sheet--empty', count === 0)
  }

  const applyFilter = () => {
    const visibleCount = commentList.applyFilter((item) => state.filter === 'all' || item.classList.contains('comment--flagged') || item.classList.contains('comment--kept'))
    setSheetCount(visibleCount, state.filter === 'all' ? 'comments' : (visibleCount === 1 ? 'bot reply' : 'bot replies'))
  }

  const showPostComments = () => {
    state.sheetSource = 'post'
    commentList.render(state.comments, state.deletedIds, state.session?.handle ?? '')

    for (const [commentId, reasons] of state.flagged) {
      commentList.flag(commentId, describeReasons(reasons))
      commentList.setKept(commentId, state.kept.has(commentId))
    }

    sheetEmpty.textContent = 'Comments from your post show up here.'
    state.filter = state.flagged.size > 0 ? 'flagged' : 'all'
    applyFilter()
  }

  const showHistoryComments = () => {
    const run = state.history[state.historyIndex]
    const comments = (run?.deleted ?? []).map((entry) => ({ ...entry, handle: entry.handle ?? 'unknown', created_at: null, like_count: 0, user_id: '', replies: [] }))
    state.sheetSource = 'history'
    commentList.render(comments, [], '')
    sheetEmpty.textContent = 'Deleted comments show up here.'
    setSheetCount(comments.length, 'deleted')
  }

  const renderTitle = (view) => {
    const selectedCount = selectedIds().length

    if (view === 'loading') {
      setTitle('One moment', '')
    } else if (view === 'connect') {
      setTitle('Connect', 'your TikTok login.')
    } else if (view === 'ready') {
      setTitle('Paste the link', 'to your post.')
    } else if (view === 'scanning') {
      setTitle('Reading', 'your comments.')
    } else if (view === 'review' && state.flagged.size === 0) {
      setTitle('No bot replies', 'on this post.')
    } else if (view === 'review') {
      setTitle(plural(selectedCount, 'bot reply', 'bot replies'), `from ${plural(accountCount(selectedIds()), 'account')}.`)
    } else if (view === 'deleting') {
      setTitle('Deleting', `${state.deletedCount} of ${state.deleteTotal}.`)
    } else if (view === 'done') {
      setTitle(`Deleted ${state.deletedCount.toLocaleString('en')}`, state.deletedCount === 1 ? 'bot reply.' : 'bot replies.')
    } else if (view === 'history') {
      setTitle('What Bob', 'has deleted.')
    } else {
      setTitle('How strict', 'Bob should be.')
    }
  }

  const renderHistory = () => {
    historyText.textContent = state.history.length === 0
      ? 'Nothing has been deleted yet. Finished clean-ups are listed here.'
      : 'Pick a clean-up to see what was removed.'
    historyRuns.replaceChildren(...state.history.map((run, index) => {
      const item = createElement('li')
      const button = createElement('button', index === state.historyIndex ? 'runs__item runs__item--active' : 'runs__item')
      button.type = 'button'
      button.dataset.run = String(index)
      button.append(createElement('span', '', formatStamp(run.finished_at)), createElement('span', 'runs__count', `${run.deleted.length.toLocaleString('en')} deleted`))
      item.append(button)

      return item
    }))
  }

  const render = () => {
    const view = currentView()
    const selectedCount = selectedIds().length
    const activeStep = STEP_BY_VIEW[view]
    const hasFlagged = state.flagged.size > 0

    for (const element of views) {
      element.hidden = element.dataset.view !== view
    }

    for (const step of steps) {
      const isActive = step.dataset.step === activeStep
      const isDone = activeStep !== undefined && STEP_ORDER.indexOf(step.dataset.step) < STEP_ORDER.indexOf(activeStep)
      step.classList.toggle('stepper__step--active', isActive)
      step.classList.toggle('stepper__step--done', isDone)
      step.toggleAttribute('aria-current', isActive)
    }

    for (const link of routeLinks) {
      const target = link.dataset.routeLink
      const isActive = target === view || (target === 'login' && view === 'connect') || (target === 'home' && !EXTRA_ROUTES.includes(view) && view !== 'connect')
      link.classList.toggle('sidebar__link--active', isActive)
      link.toggleAttribute('aria-current', isActive)
    }

    guideSheet.hidden = view !== 'connect'
    commentSheet.hidden = view === 'connect'
    commentSheet.classList.toggle('sheet--locked', view !== 'review')
    commentSheet.classList.toggle('sheet--plain', view === 'history')
    filter.hidden = view === 'history' || !hasFlagged || !['review', 'deleting'].includes(view)
    sessionBlock.hidden = !state.session
    sessionHandle.textContent = state.session ? `@${state.session.handle}` : ''
    sessionInitial.textContent = state.session ? state.session.handle.charAt(0) : ''
    cancelLogin.hidden = !state.session
    renderTitle(view)

    progress.textContent = state.topLevelCount === 0
      ? 'Opening the post.'
      : `${plural(state.topLevelCount, 'comment')} and ${plural(state.replyCount, 'reply', 'replies')} so far.`
    reviewText.textContent = hasFlagged
      ? 'Bot replies are tinted red in the list. Press Keep on anything that is genuine, then delete the rest.'
      : 'Nothing on this post matched the bot rules, so there is nothing to delete.'
    deleteLabel.textContent = `Delete ${plural(selectedCount, 'Comment')}`
    deleteLabel.disabled = selectedCount === 0
    deleteLabel.hidden = !hasFlagged
    reviewReset.hidden = hasFlagged
    reviewAnother.hidden = !hasFlagged
    reviewActions.hidden = state.isConfirming
    confirm.hidden = !state.isConfirming
    confirmLabel.textContent = `Yes, Delete ${selectedCount.toLocaleString('en')}`

    for (const option of filter.querySelectorAll('[data-filter-value]')) {
      const isActive = option.dataset.filterValue === state.filter
      option.classList.toggle('segmented__option--active', isActive)
      option.setAttribute('aria-pressed', String(isActive))
    }

    if (view === 'history') {
      renderHistory()
    }

    const serialisedSettings = JSON.stringify(state.settings)

    if (serialisedSettings !== state.lastSettings) {
      state.lastSettings = serialisedSettings

      for (const [name, value] of Object.entries(state.settings)) {
        settingsForm.elements.namedItem(name).value = value
      }
    }
  }

  const syncSheet = () => {
    const wanted = currentView() === 'history' ? 'history' : 'post'

    if (wanted === 'history') {
      showHistoryComments()
    } else if (state.sheetSource !== 'post') {
      showPostComments()
    }
  }

  const readRoute = () => {
    const route = window.location.hash.replace(/^#\/?/, '')
    state.route = EXTRA_ROUTES.includes(route) ? route : ''
    showNotice('')
    syncSheet()
    render()
  }

  const goToFlow = () => {
    if (state.route) {
      window.location.hash = '#/'
    }
  }

  const indexComments = (comments) => {
    state.commentsById.clear()
    state.topLevelCount = comments.length
    state.replyCount = 0

    for (const comment of comments) {
      state.commentsById.set(comment.comment_id, comment)
      state.replyCount += comment.replies.length

      for (const reply of comment.replies) {
        state.commentsById.set(reply.comment_id, reply)
      }
    }
  }

  const applyState = (payload, { shouldRenderSheet = true } = {}) => {
    if (payload.instance === state.instance && payload.sequence <= state.sequence) {
      return
    }

    state.instance = payload.instance
    state.sequence = payload.sequence
    state.phase = payload.phase
    state.session = payload.session
    state.settings = payload.settings
    state.flagged = new Map(Object.entries(payload.flagged))
    state.kept = new Set([...state.kept].filter((commentId) => state.flagged.has(commentId)))
    state.isConfirming = false

    if (shouldRenderSheet) {
      state.comments = payload.comments
      state.deletedIds = payload.deleted_ids
      indexComments(payload.comments)

      if (currentView() !== 'history') {
        showPostComments()
      }
    }

    if (payload.url) {
      urlInput.value = payload.url
    }

    showNotice(payload.message)
    render()
  }

  const loadHistory = async () => {
    state.history = (await request('/api/history')).runs
    state.historyIndex = 0
    render()
  }

  const run = async (button, busyLabel, action) => {
    const label = button?.textContent

    if (button) {
      button.disabled = true
      button.textContent = busyLabel
    }

    try {
      showNotice('')
      await action()
    } catch (E) {
      showNotice(E.message)
    } finally {
      if (button) {
        button.disabled = false
        button.textContent = label
      }
    }
  }

  const connect = (button, cookies) => run(button, 'Connecting', async () => {
    const payload = await request('/api/login', { cookies })
    state.isChangingLogin = false
    applyState(payload)
  })

  const startScan = (button, shouldRefresh) => run(button, 'Opening', async () => {
    state.deletedCount = 0
    state.kept.clear()
    applyState(await request('/api/scan', { url: urlInput.value, refresh: shouldRefresh }))
  })

  const actions = {
    'change-login'() {
      state.isChangingLogin = true
      goToFlow()
      showNotice('')
      render()
    },

    'cancel-login'() {
      state.isChangingLogin = false
      render()
    },

    'ask-delete'() {
      state.isConfirming = true
      render()
      requireElement('[data-action="cancel-delete"]').focus()
    },

    'cancel-delete'() {
      state.isConfirming = false
      render()
    },

    delete(button) {
      const commentIds = selectedIds()

      return run(button, 'Starting', async () => {
        state.deletedCount = 0
        state.deleteTotal = commentIds.length
        applyState(await request('/api/delete', { comment_ids: commentIds }), { shouldRenderSheet: false })
      })
    },

    stop: (button) => run(button, 'Stopping', () => request('/api/stop', {})),

    rescan: (button) => startScan(button, true),

    reset: (button) => run(button, 'One Moment', async () => {
      state.deletedCount = 0
      urlInput.value = ''
      applyState(await request('/api/reset', {}))
      urlInput.focus()
    }),

    'reset-settings'() {
      for (const [name, value] of Object.entries(SETTING_DEFAULTS)) {
        settingsForm.elements.namedItem(name).value = value
      }
    },

    'toggle-sidebar'() {
      setSidebarCollapsed(!sidebar.classList.contains('sidebar--collapsed'))
    },

    'toggle-log'() {
      drawer.hidden = !drawer.hidden
      logLabel.textContent = drawer.hidden ? 'Show Log' : 'Hide Log'
      logToggle.classList.toggle('sidebar__link--on', !drawer.hidden)
      logToggle.setAttribute('aria-expanded', String(!drawer.hidden))
      terminal.scrollToEnd()
    }
  }

  document.addEventListener('click', (event) => {
    const button = event.target.closest('[data-action]')

    if (button) {
      actions[button.dataset.action]?.(button)
    }
  })

  filter.addEventListener('click', (event) => {
    const option = event.target.closest('[data-filter-value]')

    if (option) {
      state.filter = option.dataset.filterValue
      applyFilter()
      render()
    }
  })

  historyRuns.addEventListener('click', (event) => {
    const button = event.target.closest('[data-run]')

    if (button) {
      state.historyIndex = Number(button.dataset.run)
      showHistoryComments()
      render()
    }
  })

  requireElement('[data-form="scan"]').addEventListener('submit', (event) => {
    event.preventDefault()
    startScan(event.submitter, false)
  })

  settingsForm.addEventListener('submit', (event) => {
    event.preventDefault()
    run(event.submitter, 'Saving', async () => {
      const settings = Object.fromEntries(Object.keys(SETTING_DEFAULTS).map((name) => [name, Number(settingsForm.elements.namedItem(name).value)]))
      applyState(await request('/api/settings', settings))
      showNotice('Saved.', false)
    })
  })

  const connectFrom = async (readText) => {
    dropzone.classList.remove('dropzone--over')
    dropzoneTitle.textContent = 'Connecting'
    dropzone.classList.add('dropzone--busy')

    try {
      await connect(null, await readText())
    } finally {
      dropzoneTitle.textContent = 'Drag your cookie file here'
      dropzone.classList.remove('dropzone--busy')
    }
  }

  dropzone.addEventListener('dragover', (event) => {
    event.preventDefault()
    dropzone.classList.add('dropzone--over')
  })

  dropzone.addEventListener('dragleave', () => {
    dropzone.classList.remove('dropzone--over')
  })

  dropzone.addEventListener('drop', (event) => {
    event.preventDefault()
    const file = event.dataTransfer?.files?.[0]
    const text = event.dataTransfer?.getData('text/plain') ?? ''
    connectFrom(() => (file ? file.text() : Promise.resolve(text)))
  })

  document.addEventListener('paste', (event) => {
    if (currentView() !== 'connect') {
      return
    }

    event.preventDefault()
    const file = event.clipboardData?.files?.[0]
    const text = event.clipboardData?.getData('text/plain') ?? ''
    connectFrom(() => (file ? file.text() : Promise.resolve(text)))
  })

  for (const eventName of ['dragover', 'drop']) {
    window.addEventListener(eventName, (event) => {
      if (!event.target.closest?.('[data-dropzone]')) {
        event.preventDefault()
      }
    })
  }

  subscribe({
    log: (entry) => terminal.log(entry),

    comment({ comment }) {
      state.comments = [...state.comments, comment]
      state.commentsById.set(comment.comment_id, comment)
      state.topLevelCount += 1
      state.replyCount += comment.replies.length

      for (const reply of comment.replies) {
        state.commentsById.set(reply.comment_id, reply)
      }

      if (state.sheetSource === 'post') {
        commentList.append(comment)
        setSheetCount(state.commentsById.size, 'comments')
      }

      render()
    },

    report: (payload) => applyState(payload),

    deleted({ comment_id: commentId, done, total }) {
      state.deletedCount = done
      state.deleteTotal = total
      state.flagged.delete(commentId)
      state.deletedIds = [...state.deletedIds, commentId]

      if (state.sheetSource === 'post') {
        commentList.remove(commentId)
        setSheetCount(Math.max(0, Number(sheetCount.textContent.replace(/,/g, '')) - 1), sheetNoun.textContent)
      }

      render()
    },

    async finished() {
      applyState(await request('/api/state'), { shouldRenderSheet: false })
      await loadHistory()
    },

    async failed({ message }) {
      applyState(await request('/api/state'), { shouldRenderSheet: false })
      showNotice(message)
    }
  })

  window.addEventListener('hashchange', readRoute)
  setSidebarCollapsed(window.localStorage.getItem('bob-sidebar-collapsed') === 'true')
  render()

  try {
    applyState(await request('/api/state'))
    await loadHistory()
  } catch (E) {
    state.session = null
    showNotice(E.message)
  }

  readRoute()
}
