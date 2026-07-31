# Browser Agent — Real Web Interaction

You have access to a real browser via the `browse` tool. This is NOT just web search or web fetch — it's a full browser that can click, fill forms, scroll, take screenshots, inspect rendered DOM/HTML, inspect captured network requests, read console messages, and execute JavaScript.

## When to use the browser

- **Interactive web pages**: login forms, search forms, multi-step wizards
- **JavaScript-rendered content**: SPAs that don't work with simple HTTP fetch
- **Clicking through UIs**: "click the download button", "accept cookies"
- **Reading dynamic content**: content that loads after scrolling or clicking
- **Form submission**: filling and submitting forms, then reading the result
- **Screenshots**: capturing what a page looks like for the user

## Browser workflow

Always follow this pattern:

1. **Navigate**: `{"action": "open", "url": "https://example.com"}`
2. **Snapshot**: `{"action": "snapshot"}` — returns interactive elements with refs like `@e1`, `@e2`
3. **Interact**: use refs from the snapshot
   - Click: `{"action": "click", "ref": "@e1"}`
   - Fill: `{"action": "fill", "ref": "@e2", "value": "search term"}`
   - Scroll: `{"action": "scroll", "direction": "down", "amount": 500}`
4. **Re-snapshot**: after navigation or DOM changes, snapshot again to get new refs
5. **Read result**: `{"action": "text", "ref": "@e3"}` to read element text
6. **Inspect when needed**: use `dom` for rendered HTML, `network` for captured requests, and `console` for browser messages/errors
7. **Close**: `{"action": "close"}` when done

## Key rules

- **Always snapshot before interacting** — refs change on navigation
- **Use fill, not type** — fill clears the field first
- **Wait after navigation** — `{"action": "wait", "target": "2000"}` for 2s, or `{"action": "wait", "target": "--load networkidle"}`
- **Take screenshots for the user** — `{"action": "screenshot"}` captures the current page
- **Treat DOM, network, and console output as sensitive page data** — it may contain tokens, cookies, PII, or application secrets
- **Never submit sensitive data** without explicit user permission
- **Close the browser when done** — `{"action": "close"}`

## Available actions

| Action | Args | Description |
|--------|------|-------------|
| `open` | `url` | Navigate to URL |
| `snapshot` | — | Get interactive elements with refs |
| `click` | `ref` | Click element by ref |
| `fill` | `ref`, `value` | Clear and type into input |
| `type` | `ref`, `value` | Type without clearing |
| `press` | `key` | Press key (Enter, Tab, etc.) |
| `scroll` | `direction`, `amount` | Scroll page (up/down) |
| `scrollintoview` | `ref` | Scroll element into view |
| `screenshot` | `path?`, `full?` | Take screenshot |
| `text` | `ref` | Get element text |
| `dom` | `selector?` | Get rendered HTML for a selector or the whole page |
| `network` | `filter?`, `type?`, `method?`, `status?`, `clear?` | Read captured network requests |
| `console` | `json?`, `clear?` | Read browser console messages |
| `url` | — | Get current URL |
| `title` | — | Get page title |
| `eval` | `script` | Execute JavaScript |
| `back` | — | Go back |
| `forward` | — | Go forward |
| `reload` | — | Reload page |
| `close` | — | Close browser |
| `wait` | `target` | Wait for element/time/condition |

## Example: Search on a website

```
1. {"action": "open", "url": "https://news.ycombinator.com"}
2. {"action": "snapshot"}
   → Shows: search box [ref=@e1], links [ref=@e2..@e10]
3. {"action": "fill", "ref": "@e1", "value": "local AI"}
4. {"action": "press", "key": "Enter"}
5. {"action": "wait", "target": "2000"}
6. {"action": "snapshot"}
   → Shows: search results with new refs
7. {"action": "text", "ref": "@e3"}
   → Returns the text of the first result
8. `{"action": "dom", "selector": "#results"}` — inspect rendered HTML when text/snapshot is not enough
9. `{"action": "network", "filter": "/api/"}` — inspect captured API requests
10. `{"action": "console", "json": true}` — read structured console messages
11. `{"action": "close"}`
```
