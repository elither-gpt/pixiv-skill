// DeepSeek Harness (dsh) plugin shell: registers the SKILL.md in this package
// with dsh's skill registry so the model can load it. All real work is done by
// scripts/pixiv.py; other agents just read SKILL.md directly and ignore this file.

import { readFile } from 'node:fs/promises'
import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

export const name = 'pixiv-skill'
export const inject = ['skills']

const root = dirname(dirname(fileURLToPath(import.meta.url)))
const skillPath = join(root, 'SKILL.md')
const BUNDLED_SKILL_RANK = 600

function parse(raw) {
  const m = /^---\r?\n([\s\S]*?)\r?\n---(?:\r?\n|$)/u.exec(raw)
  if (!m) throw new Error(`pixiv-skill: ${skillPath} has no frontmatter`)
  const line = /^description:\s*(.+)$/mu.exec(m[1])
  let description = line ? line[1].trim() : ''
  if (/^["']/.test(description)) description = description.slice(1, -1).replace(/\\"/g, '"')
  if (!description) throw new Error('pixiv-skill: SKILL.md has no description')
  return { description, content: raw.slice(m[0].length).trim() }
}

export function apply(ctx) {
  const { description } = parse(readFileSync(skillPath, 'utf8'))
  const candidate = {
    name: 'pixiv',
    description,
    invocation: { modelInvocable: true, userInvocable: true },
    provider: 'pixiv-skill',
    source: 'bundled',
    rank: BUNDLED_SKILL_RANK,
    resourceBase: { kind: 'directory', path: root.split('\\').join('/') },
    locator: skillPath,
  }
  ctx.skills.registerProvider(() => ({
    name: 'pixiv-skill',
    list: () => Promise.resolve([candidate]),
    async get(c, options) {
      const { rank: _rank, locator, ...summary } = c
      const raw = await readFile(locator, { encoding: 'utf8', signal: options?.signal })
      return { ...summary, content: parse(raw).content }
    },
  }))
}
