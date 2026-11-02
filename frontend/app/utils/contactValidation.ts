/**
 * Contact-field guards shared by every form that writes a person record
 * (patients, leads). Pure functions, so they are unit-tested without
 * mounting a form.
 *
 * The server stays the authority; these mirror what it accepts so a value
 * that passes here is not rejected there:
 *   - email: single @, no spaces/leading-dot/double-dot, dot in the domain,
 *     2+ char TLD, ≤254 chars — pydantic's EmailStr rejects @a@b, a@b and
 *     a..b@example.com, and so must we.
 *   - phone: allowed punctuation only, ≥6 digits, within the column width
 *     (32 for the lead, 20 for the patient record). Mirrored by
 *     ``validate_phone`` in patients/schemas.py.
 *   - date_of_birth: a real date, not in the future, not older than 120y.
 */

const PHONE_ALLOWED = /^[0-9+()\-./\s]+$/
const EMAIL_LOCAL = /^[A-Za-z0-9!#$%&'*+/=?^_\u0060{|}~.-]+$/
const EMAIL_DOMAIN = /^[A-Za-z0-9]([A-Za-z0-9-]*[A-Za-z0-9])?(\.[A-Za-z0-9]([A-Za-z0-9-]*[A-Za-z0-9])?)+$/

/** Width of the ``patients.phone`` column. */
export const PATIENT_PHONE_MAX_LENGTH = 20

/**
 * A pragmatic email check: strict about what the backend rejects,
 * tolerant about the exotic-but-legal (quoted local parts are not worth
 * the complexity here — the server would accept them, this refuses them,
 * and that is the safe direction for a typo guard).
 */
export function isValidEmail(value: string | null | undefined): boolean {
  const candidate = (value ?? '').trim()
  if (!candidate || candidate.length > 254 || /\s/.test(candidate)) return false
  const at = candidate.indexOf('@')
  if (at <= 0 || at !== candidate.lastIndexOf('@')) return false
  const local = candidate.slice(0, at)
  const domain = candidate.slice(at + 1)
  if (!local || local.length > 64) return false
  if (local.startsWith('.') || local.endsWith('.') || local.includes('..')) return false
  if (!EMAIL_LOCAL.test(local) || !EMAIL_DOMAIN.test(domain)) return false
  const tld = domain.slice(domain.lastIndexOf('.') + 1)
  return tld.length >= 2
}

export function isValidPhone(
  value: string | null | undefined,
  options: { required?: boolean, maxLength?: number } = {}
): boolean {
  const { required: isRequired = false, maxLength = 32 } = options
  const candidate = (value ?? '').trim()
  if (!candidate) return !isRequired
  if (candidate.length > maxLength) return false
  if (!PHONE_ALLOWED.test(candidate)) return false
  const digits = candidate.replace(/\D/g, '')
  return digits.length >= 6
}

export function isValidDateOfBirth(value: string | null | undefined): boolean {
  const candidate = (value ?? '').trim()
  if (!candidate) return true // optional everywhere it is used
  const parsed = new Date(`${candidate}T00:00:00`)
  if (Number.isNaN(parsed.getTime())) return false
  const endOfToday = new Date()
  endOfToday.setHours(23, 59, 59, 999)
  const earliest = new Date()
  earliest.setFullYear(earliest.getFullYear() - 120)
  earliest.setHours(0, 0, 0, 0)
  return parsed <= endOfToday && parsed >= earliest
}
