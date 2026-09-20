import { createElement } from '../lib/dom.js'

const LEVEL_WIDTH = 8
const NAME_WIDTH = 10
const MESSAGE_WIDTH = 24
const MAXIMUM_LINES = 800

const token = (text, modifier) => createElement('span', modifier ? `terminal__token terminal__token--${modifier}` : 'terminal__token', text)

const buildLine = ({ time, level, name, message, fields }) => {
  const fieldText = Object.entries(fields ?? {}).map(([key, value]) => `${key}=${value}`).join(' ')
  const line = createElement('div', 'terminal__line')

  line.append(
    token(`${time} `, 'dim'),
    token(`${level.padEnd(LEVEL_WIDTH)} `, level === 'INFO' ? 'ok' : 'alert'),
    token(`${name.padEnd(NAME_WIDTH)} `, 'dim'),
    token(fieldText ? `${message.padEnd(MESSAGE_WIDTH)}  ` : message),
    token(fieldText, 'dim')
  )

  return line
}

export const createTerminal = (screens) => ({
  log(entry) {
    for (const screen of screens) {
      const isStuckToEnd = screen.scrollTop + screen.clientHeight >= screen.scrollHeight - 24
      screen.append(buildLine(entry))

      while (screen.childElementCount > MAXIMUM_LINES) {
        screen.firstElementChild.remove()
      }

      if (isStuckToEnd) {
        screen.scrollTop = screen.scrollHeight
      }
    }
  },

  scrollToEnd() {
    for (const screen of screens) {
      screen.scrollTop = screen.scrollHeight
    }
  }
})
