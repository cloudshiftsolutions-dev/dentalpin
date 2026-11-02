import type { PatientAddress } from '~~/app/types'

export function emptyPatientAddress(country: string | null | undefined): PatientAddress {
  return { street: '', city: '', postal_code: '', province: '', country: country || 'ES' }
}

/**
 * Trimmed address for the API, or ``null`` when nothing but the country
 * was filled in — a lone default country is not an address.
 */
export function patientAddressPayload(address: PatientAddress | null | undefined): PatientAddress | null {
  if (!address) return null
  const trimmed: PatientAddress = {
    street: address.street?.trim() || undefined,
    city: address.city?.trim() || undefined,
    postal_code: address.postal_code?.trim() || undefined,
    province: address.province?.trim() || undefined,
    country: address.country?.trim() || undefined
  }
  const hasContent = Boolean(trimmed.street || trimmed.city || trimmed.postal_code || trimmed.province)
  return hasContent ? trimmed : null
}
