// @vitest-environment node
import { describe, expect, it } from 'vitest'
import {
  computeAge,
  dateOfBirthFromAge
} from '#module-layers/patients/frontend/utils/medicalSnapshot'
import {
  emptyPatientAddress,
  patientAddressPayload
} from '#module-layers/patients/frontend/utils/patientAddress'
import { isValidPhone, PATIENT_PHONE_MAX_LENGTH } from '~~/app/utils/contactValidation'

describe('dateOfBirthFromAge', () => {
  const today = new Date(2026, 10, 2) // 2 Nov 2026

  it('goes back N years from today so the age reads back exactly', () => {
    expect(dateOfBirthFromAge(34, today)).toBe('1992-11-02')
    expect(dateOfBirthFromAge(0, today)).toBe('2026-11-02')
    expect(computeAge(dateOfBirthFromAge(34))).toBe(34)
  })

  it('maps 29 February to the 28th so the year always exists', () => {
    expect(dateOfBirthFromAge(5, new Date(2028, 1, 29))).toBe('2023-02-28')
  })

  it('rejects ages that are not whole years in range', () => {
    for (const age of [-1, 121, 3.5, Number.NaN, null, undefined]) {
      expect(dateOfBirthFromAge(age as number, today), String(age)).toBeNull()
    }
  })
})

describe('patientAddressPayload', () => {
  it('returns null when only the default country is set', () => {
    expect(patientAddressPayload(emptyPatientAddress('IN'))).toBeNull()
    expect(patientAddressPayload(null)).toBeNull()
  })

  it('keeps a partial address, trimmed, without needing a street', () => {
    expect(patientAddressPayload({ ...emptyPatientAddress('IN'), city: '  Coimbatore ' })).toEqual({
      street: undefined,
      city: 'Coimbatore',
      postal_code: undefined,
      province: undefined,
      country: 'IN'
    })
  })

  it('defaults the country to ES when the clinic has none', () => {
    expect(emptyPatientAddress(null).country).toBe('ES')
  })
})

describe('patient phone rule', () => {
  it('accepts Indian formats and rejects letters', () => {
    const opts = { maxLength: PATIENT_PHONE_MAX_LENGTH }
    expect(isValidPhone('+91 98765 43210', opts)).toBe(true)
    expect(isValidPhone('9876543210', opts)).toBe(true)
    expect(isValidPhone('98765abcde', opts)).toBe(false)
    expect(isValidPhone('abcdefghij', opts)).toBe(false)
  })
})
