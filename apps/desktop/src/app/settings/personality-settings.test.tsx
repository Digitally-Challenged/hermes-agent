import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const getHermesConfig = vi.fn()
const saveHermesConfig = vi.fn()
const savePersonalities = vi.fn()

vi.mock('@/hermes', () => ({
  getHermesConfig: () => getHermesConfig(),
  saveHermesConfig: (config: unknown, profile?: unknown) => saveHermesConfig(config, profile),
  savePersonalities: (personalities: unknown, profile?: unknown) => savePersonalities(personalities, profile)
}))

vi.mock('@/store/session', async () => {
  const { atom } = await import('nanostores')

  return { $currentPersonality: atom('kawaii') }
})

vi.mock('@/store/notifications', () => ({
  notify: vi.fn(),
  notifyError: vi.fn()
}))

import { PersonalitySettings } from './personality-settings'

beforeEach(() => {
  vi.clearAllMocks()
  getHermesConfig.mockResolvedValue({
    display: { personality: 'concise' },
    agent: { personalities: { coder: { system_prompt: 'be terse', tone: 'dry' } } }
  })
  saveHermesConfig.mockResolvedValue({ ok: true })
  savePersonalities.mockResolvedValue({ ok: true })
})

afterEach(() => cleanup())

describe('PersonalitySettings', () => {
  it('promotes the current session style to the default', async () => {
    render(<PersonalitySettings />)

    // Panel loads, and the current ("kawaii") differs from the default ("concise").
    expect(await screen.findByText('Assistant styles')).toBeTruthy()
    expect(await screen.findByText(/Current: kawaii/)).toBeTruthy()

    fireEvent.click(screen.getByText('Make default'))

    await waitFor(() => {
      expect(saveHermesConfig).toHaveBeenCalledWith({ display: { personality: 'kawaii' } }, undefined)
    })
  })

  it('authors a new custom style through the manager modal', async () => {
    render(<PersonalitySettings />)

    expect(await screen.findByText('Assistant styles')).toBeTruthy()
    fireEvent.click(screen.getByText('Manage styles…'))

    // Built-ins plus the existing custom style are listed.
    expect(await screen.findByText('coder')).toBeTruthy()
    expect(screen.getByText('helpful')).toBeTruthy()

    fireEvent.click(screen.getByText('New style'))
    fireEvent.change(screen.getByPlaceholderText('e.g. coder'), { target: { value: 'My Style' } })
    fireEvent.change(screen.getByPlaceholderText(/How this style should behave/), {
      target: { value: 'be friendly' }
    })

    fireEvent.click(screen.getByText('Save'))

    await waitFor(() => {
      expect(savePersonalities).toHaveBeenCalledTimes(1)
      const map = savePersonalities.mock.calls[0][0] as Record<string, unknown>
      expect(map['my-style']).toEqual({ system_prompt: 'be friendly' })
      expect(map.coder).toEqual({ system_prompt: 'be terse', tone: 'dry' })
    })
  })
})
