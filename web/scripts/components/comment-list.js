import { createElement } from '../lib/dom.js'
import { avatarColour, formatAge } from '../lib/format.js'

const HEART_ICON = '<svg class="comment__heart" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round" aria-hidden="true" focusable="false"><path d="M12 20.5s-7.5-4.4-7.5-10A4.3 4.3 0 0 1 12 8a4.3 4.3 0 0 1 7.5 2.5c0 5.6-7.5 10-7.5 10Z"/></svg>'
const IMAGE_ONLY_TEXT = 'Image or sticker'

const prefersReducedMotion = () => window.matchMedia('(prefers-reduced-motion: reduce)').matches

const renderComment = (comment, isReply, ownerHandle) => {
  const handle = comment.handle || 'unknown'
  const item = createElement('li', isReply ? 'comment comment--reply' : 'comment')
  const clip = createElement('div', 'comment__clip')
  const content = createElement('div', 'comment__content')
  const body = createElement('div', 'comment__body')

  const avatar = createElement('span', 'comment__avatar', handle.charAt(0))
  avatar.style.backgroundColor = avatarColour(handle)
  avatar.setAttribute('aria-hidden', 'true')

  const author = createElement('p', 'comment__author', handle)

  if (handle === ownerHandle) {
    author.append(createElement('span', 'comment__creator', 'Creator'))
  }

  const keep = createElement('button', 'comment__keep', 'Keep')
  keep.type = 'button'
  keep.dataset.keep = comment.comment_id

  const meta = createElement('p', 'comment__meta')
  meta.append(createElement('span', 'comment__age', formatAge(comment.created_at)), keep, createElement('span', 'comment__reason'))

  const likes = createElement('span', 'comment__likes')
  likes.innerHTML = HEART_ICON
  const likeCount = createElement('span', 'comment__like-count', comment.like_count > 0 ? comment.like_count.toLocaleString('en') : '')
  likeCount.setAttribute('aria-hidden', 'true')
  likes.append(likeCount, createElement('span', 'visually-hidden', `${comment.like_count} likes`))

  body.append(author, createElement('p', 'comment__text', comment.text || IMAGE_ONLY_TEXT), meta)
  content.append(avatar, body, likes)
  clip.append(content)
  item.append(clip)
  item.dataset.commentId = comment.comment_id
  item.dataset.userId = comment.user_id ?? ''

  return item
}

export const createCommentList = ({ list, onKeepChange = () => {} }) => {
  const items = new Map()
  let ownerHandle = ''

  const appendThread = (comment) => {
    for (const [entry, isReply] of [[comment, false], ...comment.replies.map((reply) => [reply, true])]) {
      const item = renderComment(entry, isReply, ownerHandle)
      items.set(entry.comment_id, item)
      list.append(item)
    }
  }

  const applyKept = (commentId, isKept) => {
    const item = items.get(commentId)

    if (!item || !item.dataset.reason) {
      return
    }

    item.classList.toggle('comment--kept', isKept)
    item.classList.toggle('comment--flagged', !isKept)
    item.querySelector('[data-keep]').textContent = isKept ? 'Flag Again' : 'Keep'
    item.querySelector('.comment__reason').textContent = isKept ? 'kept' : item.dataset.reason
  }

  list.addEventListener('click', (event) => {
    const button = event.target.closest('[data-keep]')

    if (button) {
      const isKept = !items.get(button.dataset.keep).classList.contains('comment--kept')
      applyKept(button.dataset.keep, isKept)
      onKeepChange(button.dataset.keep, isKept)
    }
  })

  return {
    render(comments, deletedIds, owner) {
      ownerHandle = owner
      items.clear()
      list.replaceChildren()

      for (const comment of comments) {
        appendThread(comment)
      }

      for (const commentId of deletedIds) {
        items.get(commentId)?.remove()
        items.delete(commentId)
      }

      list.scrollTop = 0
    },

    append(comment) {
      const isStuckToEnd = list.scrollTop + list.clientHeight >= list.scrollHeight - 48
      appendThread(comment)

      if (isStuckToEnd) {
        list.scrollTop = list.scrollHeight
      }
    },

    flag(commentId, explanation) {
      const item = items.get(commentId)

      if (item) {
        item.dataset.reason = explanation
        item.querySelector('.comment__reason').textContent = explanation
        item.classList.add('comment--flagged')
      }
    },

    setKept: applyKept,

    remove(commentId) {
      const item = items.get(commentId)

      if (!item) {
        return
      }

      if (!item.hidden) {
        const top = item.offsetTop - list.offsetTop

        if (top < list.scrollTop || top + item.offsetHeight > list.scrollTop + list.clientHeight) {
          list.scrollTo({ top: top - list.clientHeight / 3, behavior: prefersReducedMotion() ? 'auto' : 'smooth' })
        }
      }

      item.classList.add('comment--deleting')
      window.setTimeout(() => item.classList.add('comment--deleted'), prefersReducedMotion() ? 0 : 350)
    },

    applyFilter(isVisible) {
      let visibleCount = 0

      for (const item of items.values()) {
        const isShown = isVisible(item)
        item.hidden = !isShown
        visibleCount += isShown ? 1 : 0
      }

      list.scrollTop = 0

      return visibleCount
    },

    setLocked(isLocked) {
      list.closest('.sheet')?.classList.toggle('sheet--locked', isLocked)
    }
  }
}
