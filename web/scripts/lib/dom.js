export const createElement = (tag, className, text) => {
  const element = document.createElement(tag)

  if (className) {
    element.className = className
  }

  if (text !== undefined && text !== null) {
    element.textContent = text
  }

  return element
}

export const requireElement = (selector, root = document) => {
  const element = root.querySelector(selector)

  if (!element) {
    throw new Error(`Missing element: ${selector}`)
  }

  return element
}
