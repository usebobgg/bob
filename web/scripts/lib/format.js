const MINUTE = 60
const HOUR = 3600
const DAY = 86400
const WEEK = 604800

export const formatAge = (createdAt) => {
  if (!createdAt) {
    return ''
  }

  const seconds = Math.max(0, Math.floor(Date.now() / 1000) - createdAt)

  if (seconds < HOUR) {
    return `${Math.max(1, Math.floor(seconds / MINUTE))}m`
  }

  if (seconds < DAY) {
    return `${Math.floor(seconds / HOUR)}h`
  }

  if (seconds < WEEK) {
    return `${Math.floor(seconds / DAY)}d`
  }

  return `${Math.floor(seconds / WEEK)}w`
}

export const avatarColour = (handle) => {
  let hash = 0

  for (const character of handle) {
    hash = (hash * 31 + character.codePointAt(0)) % 360
  }

  return `oklch(0.82 0.08 ${hash})`
}

export const describeReasons = (reasons) => {
  const isDuplicate = reasons.includes('duplicate_reply')
  const isExcessive = reasons.includes('excessive_replies')

  if (isDuplicate && isExcessive) {
    return 'Same reply, under too many comments'
  }

  return isDuplicate ? 'Same reply, posted again and again' : 'Replies under too many comments'
}

export const plural = (count, singular, pluralForm = `${singular}s`) => `${count.toLocaleString('en')} ${count === 1 ? singular : pluralForm}`

export const formatStamp = (stamp) => {
  const match = /^(\d{4})(\d{2})(\d{2})T(\d{2})(\d{2})(\d{2})Z$/.exec(stamp)

  if (!match) {
    return stamp
  }

  const [, year, month, day, hour, minute, second] = match
  const date = new Date(Date.UTC(Number(year), Number(month) - 1, Number(day), Number(hour), Number(minute), Number(second)))

  return date.toLocaleString('en', { dateStyle: 'medium', timeStyle: 'short' })
}
