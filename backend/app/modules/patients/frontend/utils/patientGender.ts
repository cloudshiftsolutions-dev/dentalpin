import type { PatientExtended } from '~~/app/types'

export type PatientGender = NonNullable<PatientExtended['gender']>

/** Stored value → i18n key. Values match ``Gender`` in patients/schemas.py. */
export const GENDER_LABEL_KEYS: Record<PatientGender, string> = {
  male: 'patients.gender.male',
  female: 'patients.gender.female',
  other: 'patients.gender.other',
  prefer_not_say: 'patients.gender.preferNotSay'
}

export function buildGenderOptions(t: (key: string) => string): { label: string, value: PatientGender }[] {
  return (Object.keys(GENDER_LABEL_KEYS) as PatientGender[]).map(value => ({
    label: t(GENDER_LABEL_KEYS[value]),
    value
  }))
}
