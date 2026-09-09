import { useStore } from '@nanostores/react'
import { useCallback, useEffect, useState } from 'react'

import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import { getHermesConfig, saveHermesConfig, savePersonalities } from '@/hermes'
import { normalizePersonalityValue } from '@/lib/chat-runtime'
import { Plus, SlidersHorizontal, Trash2 } from '@/lib/icons'
import { BUILTIN_PERSONALITIES } from '@/lib/personalities'
import { notify, notifyError } from '@/store/notifications'
import { $currentPersonality } from '@/store/session'

import { ListRow, Pill } from './primitives'

// A custom style is the same shape the backend renderer reads
// (render_personality_prompt): snake_case system_prompt / tone / style.
interface CustomStyle {
  system_prompt: string
  tone?: string
  style?: string
}

type CustomStyles = Record<string, CustomStyle>

function isCustomStyles(value: unknown): value is CustomStyles {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

// Canonical form of a user-entered name: lowercase, spaces -> dashes, drop
// anything that isn't [a-z0-9_-]. Mirrors the backend's safe key charset.
function slugify(name: string): string {
  return name
    .toLowerCase()
    .trim()
    .replace(/\s+/g, '-')
    .replace(/[^a-z0-9_-]/g, '')
}

interface FormDraft {
  name: string
  system_prompt: string
  tone: string
  style: string
}

const EMPTY_DRAFT: FormDraft = { name: '', system_prompt: '', tone: '', style: '' }

export function PersonalitySettings({ profile = null }: { profile?: null | string }) {
  const currentPersonality = useStore($currentPersonality)
  const [defaultName, setDefaultName] = useState('')
  const [custom, setCustom] = useState<CustomStyles>({})
  const [loadError, setLoadError] = useState<null | string>(null)
  const [open, setOpen] = useState(false)

  const refresh = useCallback(async () => {
    try {
      const config = await getHermesConfig(profile ?? undefined)
      const personalities = config.agent?.personalities
      setDefaultName(normalizePersonalityValue(config.display?.personality ?? ''))
      setCustom(isCustomStyles(personalities) ? personalities : {})
      setLoadError(null)
    } catch (err) {
      setLoadError(err instanceof Error ? err.message : 'Assistant styles failed to load')
    }
  }, [profile])

  useEffect(() => {
    void refresh()
  }, [refresh])

  const makeDefault = async (name: string) => {
    try {
      await saveHermesConfig({ display: { personality: name } }, profile ?? undefined)
      setDefaultName(normalizePersonalityValue(name))
      notify({ kind: 'success', title: 'Default assistant style', message: 'New sessions will use this style.' })
    } catch (err) {
      notifyError(err, 'Failed to set default style')
    }
  }

  const currentIsDefault = normalizePersonalityValue(currentPersonality) === defaultName

  if (loadError) {
    return (
      <div className="flex items-center justify-between gap-3 py-2">
        <span className="text-[length:var(--conversation-caption-font-size)] text-muted-foreground">
          Assistant styles failed to load: {loadError}
        </span>
        <Button onClick={() => void refresh()} size="sm" type="button" variant="secondary">
          Retry
        </Button>
      </div>
    )
  }

  return (
    <section className="py-1">
      <div className="flex items-center gap-2 py-2">
        <span className="min-w-0 flex-1 text-[length:var(--conversation-text-font-size)] font-medium text-foreground">
          Assistant styles
        </span>
        <Button onClick={() => setOpen(true)} size="sm" type="button" variant="secondary">
          <SlidersHorizontal className="size-3.5" />
          Manage styles…
        </Button>
      </div>

      {currentPersonality && !currentIsDefault && (
        <div className="ml-1.5 border-l-2 border-(--ui-accent-secondary)/25 pl-4 pr-4">
          <ListRow
            action={
              <Button onClick={() => void makeDefault(currentPersonality)} size="sm" type="button" variant="secondary">
                Make default
              </Button>
            }
            description="The style this session is using."
            title={<span className="flex items-center gap-2">Current: {currentPersonality}</span>}
          />
        </div>
      )}

      <PersonalityManagerModal
        custom={custom}
        defaultName={defaultName}
        onChanged={refresh}
        onOpenChange={setOpen}
        onSetDefault={name => void makeDefault(name)}
        open={open}
        profile={profile}
      />
    </section>
  )
}

function PersonalityManagerModal({
  custom,
  defaultName,
  profile,
  open,
  onOpenChange,
  onChanged,
  onSetDefault
}: {
  custom: CustomStyles
  defaultName: string
  profile: null | string
  open: boolean
  onOpenChange: (open: boolean) => void
  onChanged: () => Promise<void> | void
  onSetDefault: (name: string) => Promise<void> | void
}) {
  const [editing, setEditing] = useState<null | string>(null)
  const [draft, setDraft] = useState<FormDraft>(EMPTY_DRAFT)
  const [saving, setSaving] = useState(false)

  const isNew = editing === '__new__'

  useEffect(() => {
    if (!open) {
      setEditing(null)
      setDraft(EMPTY_DRAFT)
    }
  }, [open])

  const beginEdit = (name: string | null) => {
    setEditing(name)

    if (name) {
      const style = custom[name]
      setDraft({
        name,
        system_prompt: style?.system_prompt ?? '',
        tone: style?.tone ?? '',
        style: style?.style ?? ''
      })
    } else {
      setDraft(EMPTY_DRAFT)
      setEditing('__new__')
    }
  }

  const persist = async (next: CustomStyles) => {
    setSaving(true)

    try {
      await savePersonalities(next, profile ?? undefined)
      notify({ kind: 'success', title: 'Assistant styles saved', message: 'Custom styles updated.' })
      await onChanged()
      setEditing(null)
      setDraft(EMPTY_DRAFT)
    } catch (err) {
      notifyError(err, 'Failed to save assistant styles')
    } finally {
      setSaving(false)
    }
  }

  const saveDraft = async () => {
    const name = slugify(draft.name)

    if (!name) {
      notifyError(new Error('Name is required'), 'Invalid style name')

      return
    }

    if (!draft.system_prompt.trim()) {
      notifyError(new Error('System prompt is required'), 'Invalid style')

      return
    }

    const definition: CustomStyle = { system_prompt: draft.system_prompt.trim() }

    if (draft.tone.trim()) {
      definition.tone = draft.tone.trim()
    }

    if (draft.style.trim()) {
      definition.style = draft.style.trim()
    }

    const next: CustomStyles = { ...custom }

    if (!isNew && editing && editing !== name) {
      delete next[editing]
    }

    next[name] = definition
    await persist(next)
  }

  const deleteStyle = async (name: string) => {
    const next: CustomStyles = { ...custom }
    delete next[name]
    await persist(next)
  }

  const customNames = Object.keys(custom)
  const allNames = [...new Set([...BUILTIN_PERSONALITIES, ...customNames])]

  return (
    <Dialog onOpenChange={onOpenChange} open={open}>
      <DialogContent bodyClassName="dt-portal-scrollbar" className="max-w-xl">
        <DialogHeader>
          <DialogTitle icon={SlidersHorizontal}>Assistant styles</DialogTitle>
          <DialogDescription>
            Custom styles you write yourself, plus the built-ins. Pick one to make it the default for new sessions.
          </DialogDescription>
        </DialogHeader>

        <div className="min-w-0 space-y-1">
          {allNames.map(name => {
            const builtin = BUILTIN_PERSONALITIES.includes(name)
            const preview = custom[name]?.system_prompt

            return (
              <div className="border-b border-border/40 last:border-b-0" key={name}>
                <ListRow
                  action={
                    <div className="flex items-center gap-1">
                      {defaultName === name ? <Pill>default</Pill> : null}
                      {!builtin ? (
                        <>
                          <Button onClick={() => beginEdit(name)} size="sm" type="button" variant="ghost">
                            Edit
                          </Button>
                          <Button
                            aria-label={`Delete ${name}`}
                            onClick={() => void deleteStyle(name)}
                            size="sm"
                            type="button"
                            variant="ghost"
                          >
                            <Trash2 className="size-3.5" />
                          </Button>
                        </>
                      ) : null}
                      {defaultName !== name ? (
                        <Button onClick={() => void onSetDefault(name)} size="sm" type="button" variant="secondary">
                          Set default
                        </Button>
                      ) : null}
                    </div>
                  }
                  description={builtin ? 'Built-in' : preview}
                  title={name}
                />
              </div>
            )
          })}
        </div>

        {editing ? (
          <div className="mt-4 space-y-3 rounded-lg border border-border/40 p-3">
            {isNew ? (
              <label className="block space-y-1">
                <span className="text-[length:var(--conversation-caption-font-size)] text-muted-foreground">Name</span>
                <Input
                  onChange={e => setDraft(d => ({ ...d, name: e.target.value }))}
                  placeholder="e.g. coder"
                  value={draft.name}
                />
              </label>
            ) : null}
            <label className="block space-y-1">
              <span className="text-[length:var(--conversation-caption-font-size)] text-muted-foreground">
                System prompt
              </span>
              <Textarea
                onChange={e => setDraft(d => ({ ...d, system_prompt: e.target.value }))}
                placeholder="How this style should behave, e.g. 'You are a terse senior engineer.'"
                value={draft.system_prompt}
              />
            </label>
            <label className="block space-y-1">
              <span className="text-[length:var(--conversation-caption-font-size)] text-muted-foreground">Tone</span>
              <Input
                onChange={e => setDraft(d => ({ ...d, tone: e.target.value }))}
                placeholder="optional"
                value={draft.tone}
              />
            </label>
            <label className="block space-y-1">
              <span className="text-[length:var(--conversation-caption-font-size)] text-muted-foreground">Style</span>
              <Input
                onChange={e => setDraft(d => ({ ...d, style: e.target.value }))}
                placeholder="optional"
                value={draft.style}
              />
            </label>
            <div className="flex items-center justify-end gap-2">
              <Button onClick={() => setEditing(null)} size="sm" type="button" variant="ghost">
                Cancel
              </Button>
              <Button disabled={saving} onClick={() => void saveDraft()} size="sm">
                Save
              </Button>
            </div>
          </div>
        ) : null}

        <DialogFooter>
          <Button onClick={() => beginEdit(null)} size="sm" type="button" variant="secondary">
            <Plus className="size-3.5" />
            New style
          </Button>
          <DialogClose asChild>
            <Button size="sm" type="button" variant="ghost">
              Done
            </Button>
          </DialogClose>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
