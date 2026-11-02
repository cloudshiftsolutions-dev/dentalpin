// @vitest-environment node
import { describe, expect, it } from 'vitest'
import {
  isValidRecallInterval,
  recallMonthOf,
  recallTimingFromInterval
} from '#module-layers/recalls/frontend/utils/recallInterval'

describe('recallTimingFromInterval', () => {
  const today = new Date(2026, 10, 2) // 2 Nov 2026

  it('pins an exact date for days and weeks', () => {
    expect(recallTimingFromInterval(2, 'week', today)).toEqual({ dueMonth: '2026-11-01', dueDate: '2026-11-16' })
    expect(recallTimingFromInterval(10, 'day', new Date(2026, 10, 25))).toEqual({
      dueMonth: '2026-12-01',
      dueDate: '2026-12-05'
    })
  })

  it('keeps months as a monthly bucket with no exact day', () => {
    expect(recallTimingFromInterval(1, 'month', today)).toEqual({ dueMonth: '2026-12-01', dueDate: '' })
    expect(recallTimingFromInterval(3, 'month', new Date(2026, 10, 30))).toEqual({ dueMonth: '2027-02-01', dueDate: '' })
  })
})

describe('isValidRecallInterval', () => {
  it('accepts whole numbers within the unit cap', () => {
    expect(isValidRecallInterval(1, 'day')).toBe(true)
    expect(isValidRecallInterval(104, 'week')).toBe(true)
    expect(isValidRecallInterval(60, 'month')).toBe(true)
  })

  it('rejects zero, fractions and values over the cap', () => {
    for (const [value, unit] of [[0, 'day'], [1.5, 'week'], [105, 'week'], [61, 'month'], [null, 'day']] as const) {
      expect(isValidRecallInterval(value, unit), `${value} ${unit}`).toBe(false)
    }
  })
})

it('recallMonthOf returns day 1 of the month', () => {
  expect(recallMonthOf('2026-11-16')).toBe('2026-11-01')
})
