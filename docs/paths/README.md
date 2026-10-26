# User paths

Each page here is a lane: one kind of person, or program, using joe, step by
step from the start. A step says what to do and what you should see, and names
what checks it, on lines of its own:

```text
- spec: <a page spec's whole title>
- test: tests/<file>.py::<test function>
```

| Lane | Who | Its checks |
| --- | --- | --- |
| [The music page](music-page.md) | A person at joe's page: starting joe, analysing a recording, recording live, arranging the windows | `npx playwright test --grep @music-page` |
| [The voice loop](voice-loop.md) | A person talking with qmcp through joe, and reading back what was heard | `npx playwright test --grep @voice-loop` |
| [joe as a server](server.md) | A program: alfred through the media API, vox and qmcp through the voice routes, scripts through the library | `uv run pytest tests/` |

Every page spec carries the tag of the lane it belongs to:

```js
test('the Panels menu lists every window, says which are closed, and opens one', { tag: '@music-page' }, async ({ page }) => {
```

`npm run check:paths` holds the pages and the specs to each other. It fails
when a spec carries no lane or two, when two specs share a title, when a page
names a spec or a test there is none of, or a spec of another lane, and when a
spec is not a step of its lane's page exactly once. CI runs it with the specs.

## Changing what a person does, test first

1. Write the step on its lane's page: what the person does, and what they see.
2. Name the spec that will check it, and write that spec with the lane's tag.
   The spec is red, and so is `npm run check:paths` until the two agree.
3. Change the page until the spec is green.

A step that changes is changed on its page and in its spec together; a spec
removed leaves its page's line behind, and the check says so.
