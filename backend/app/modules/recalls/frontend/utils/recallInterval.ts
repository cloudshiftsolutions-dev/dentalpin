import type { RecallIntervalUnit } from '../composables/useRecalls'

/** Mirrors ``INTERVAL_MAX`` in recalls/schemas.py. */
export const RECALL_INTERVAL_MAX: Record<RecallIntervalUnit, number> = {
  day: 730,
  week: 104,
  month: 60
}

export const RECALL_INTERVAL_UNITS: RecallIntervalUnit[] = ['day', 'week', 'month']

export interface RecallTiming {
  /** Day 1 of the month the recall is listed under (YYYY-MM-01). */
  dueMonth: string
  /** Exact day (YYYY-MM-DD) or '' when only the month matters. */
  dueDate: string
}

function pad(n: number): string {
  return String(n).padStart(2, '0')
}

export function recallIsoDate(d: Date): string {
  return `${String(d.getFullYear()).padStart(4, '0')}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`
}

/** ``YYYY-MM-01`` of the month containing an ISO date. */
export function recallMonthOf(isoDate: string): string {
  return `${isoDate.slice(0, 7)}-01`
}

/**
 * Recall timing ``value`` ``unit``s after ``from``. Same rule as
 * ``interval_due`` in recalls/service.py: months fill the monthly
 * bucket only, days and weeks pin an exact date.
 */
export function recallTimingFromInterval(
  value: number,
  unit: RecallIntervalUnit,
  from: Date = new Date()
): RecallTiming {
  if (unit === 'month') {
    const target = new Date(from.getFullYear(), from.getMonth() + value, 1)
    return { dueMonth: recallIsoDate(target), dueDate: '' }
  }
  const days = unit === 'week' ? value * 7 : value
  const due = new Date(from.getFullYear(), from.getMonth(), from.getDate() + days)
  const dueDate = recallIsoDate(due)
  return { dueMonth: recallMonthOf(dueDate), dueDate }
}

/** A usable "in N units" value: whole, at least 1, within the unit's cap. */
export function isValidRecallInterval(value: number | null | undefined, unit: RecallIntervalUnit): boolean {
  return typeof value === 'number' && Number.isInteger(value) && value >= 1 && value <= RECALL_INTERVAL_MAX[unit]
}
